"""Legacy-compatible reports over disposable SQLite and optional PostgreSQL."""
import csv
from io import BytesIO, StringIO
from zipfile import ZipFile
import uuid

import pytest

from app.db import connect
from app.reporting import get_report


def move(admin, catalog, kind, amount, **extra):
    body = {'type': kind, 'material_id': catalog['material']['id'], 'quantity': amount}
    if kind == 'ENTRADA':
        body['destination_id'] = catalog['origin']['id']
    else:
        body.update(origin_id=catalog['origin']['id'], employee_id=catalog['employee']['id'])
    response = admin.post('/api/movements', json={**body, **extra}, headers={'Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    return response.json()['id']


def report(admin, entity, **filters):
    response = admin.get('/api/reports/' + entity, params=filters)
    assert response.status_code == 200, response.text
    return response.json()


def csv_rows(response):
    assert response.status_code == 200, response.text
    assert response.content.startswith(b'\xef\xbb\xbf')
    return list(csv.reader(StringIO(response.content.decode('utf-8-sig')), delimiter=';'))


def test_reports_require_login_and_reject_private_entities(client, admin):
    assert client.get('/api/reports/catalog').status_code == 200
    admin.post('/api/auth/logout')
    assert client.get('/api/reports/catalog').status_code == 401
    assert client.get('/api/reports/stock/export').status_code == 401


def test_catalog_states_actual_import_export_scope(admin):
    catalog = admin.get('/api/reports/catalog').json()
    assert {entry['entity'] for entry in catalog['exports']} == {'materials', 'stock', 'movements', 'loans', 'dashboard'}
    assert {entry['entity'] for entry in catalog['imports']} == {'materials', 'movements'}
    assert catalog['document_import'] is False
    for entity in ('users', 'audit', 'employees', 'attendance_facial_records'):
        assert admin.get('/api/reports/' + entity).status_code == 404


def test_stock_report_exact_quantities_and_totals_by_unit(admin, catalog):
    move(admin, catalog, 'ENTRADA', '0.300')
    move(admin, catalog, 'SAIDA', '0.125')
    data = report(admin, 'stock', material_id=catalog['material']['id'])
    assert len(data['rows']) == 1
    row = data['rows'][0]
    assert (row['available'], row['borrowed'], row['total_control']) == ('0.175', '0.125', '0.300')
    assert data['summary']['by_unit'] == [{'unit': 'UN', 'available': '0.175', 'borrowed': '0.125', 'total_control': '0.300'}]
    assert row['work_id'] == catalog['work']['id']
    assert report(admin, 'stock', work_id=catalog['other_work']['id'])['rows'] == []
    assert report(admin, 'loans')['rows'][0]['quantity'] == '0.125'


def test_no_cross_unit_sum_or_fabricated_dashboard_movements(admin, catalog):
    move(admin, catalog, 'ENTRADA', '1.001')
    catalog['create']('materials', code='KG-001', description='Areia', category_id=catalog['category']['id'],
                      unit='KG', minimum_stock=0, individualizable=False, status='ATIVO')
    data = report(admin, 'dashboard')
    assert {row['unit'] for row in data['summary']['by_unit']} == {'KG', 'UN'}
    assert data['summary']['movement_count'] == 1
    assert all('material_id' not in row and 'created_at' not in row for row in data['rows'])
    assert 'period_definition' in data['metadata']


def test_report_filters_are_literal_and_entity_specific(admin, catalog):
    assert report(admin, 'materials', q='MAT-001')['rows'][0]['id'] == catalog['material']['id']
    assert report(admin, 'materials', q='%')['rows'] == []
    for entity, query in (('stock', {'date_from': '2026-01-01'}), ('materials', {'employee_id': '1'}),
                          ('loans', {'type': 'SAIDA'}), ('movements', {'unknown': '1'}),
                          ('movements', {'date_from': '2026-02-30'}), ('movements', {'date_to': '9999-12-31'}),
                          ('movements', {'date_from': '2026-02-02', 'date_to': '2026-02-01'})):
        assert admin.get('/api/reports/' + entity, params=query).status_code == 422
    assert admin.get('/api/reports/movements?q=a&q=b').status_code == 422


def test_calendar_period_uses_timezone_and_complete_final_day(admin, catalog, monkeypatch):
    monkeypatch.setenv('COMPAC_TIMEZONE', 'America/Sao_Paulo')
    ids = [move(admin, catalog, 'ENTRADA', '0.001') for _ in range(4)]
    dates = ['2026-05-01T02:59:59+00:00', '2026-05-01T03:00:00+00:00',
             '2026-05-02T02:59:59+00:00', '2026-05-02T03:00:00+00:00']
    with connect(write=True) as db:
        for identifier, instant in zip(ids, dates):
            db.execute('UPDATE movements SET created_at=? WHERE id=?', (instant, identifier))
    data = report(admin, 'movements', date_from='2026-05-01', date_to='2026-05-01')
    assert [row['id'] for row in data['rows']] == [ids[2], ids[1]]
    assert data['metadata']['date_bounds_utc'] == {'date_from': '2026-05-01T03:00:00+00:00', 'date_to': '2026-05-02T03:00:00+00:00'}
    exported = csv_rows(admin.get('/api/reports/movements/export', params={'date_from':'2026-05-01','date_to':'2026-05-01'}))
    assert any(str(ids[1]) in row for row in exported)
    assert any(str(ids[2]) in row for row in exported)


@pytest.mark.parametrize('format_name', ['csv', 'xlsx', 'pdf', 'docx'])
def test_export_formats_empty_headers_and_formula_protection(admin, catalog, format_name):
    with connect(write=True) as db:
        db.execute('UPDATE materials SET description=? WHERE id=?', ('=HYPERLINK("unsafe")', catalog['material']['id']))
    response = admin.get('/api/reports/materials/export', params={'format': format_name, 'material_id': catalog['material']['id']})
    assert response.status_code == 200, response.text
    assert f'.{format_name}"' in response.headers['content-disposition']
    if format_name == 'csv':
        rows = csv_rows(response)
        assert any("'=HYPERLINK" in cell for row in rows for cell in row)
        empty = csv_rows(admin.get('/api/reports/loans/export'))
        assert any('Pendente' in row for row in empty)
    elif format_name == 'xlsx':
        with ZipFile(BytesIO(response.content)) as archive:
            sheets = b''.join(archive.read(name) for name in archive.namelist() if name.startswith('xl/worksheets/'))
            assert b'<f>' not in sheets
    elif format_name == 'pdf':
        assert response.content.startswith(b'%PDF-')
    else:
        with ZipFile(BytesIO(response.content)) as archive:
            assert 'word/document.xml' in archive.namelist()


def test_legacy_provenance_uses_allowlisted_audit_keys_and_real_loans(admin, catalog):
    identifier = move(admin, catalog, 'ENTRADA', '1.000')
    move(admin, catalog, 'SAIDA', '0.125')
    with connect(write=True) as db:
        db.execute('INSERT INTO audit(user_id,action,entity,record_id,details,created_at) VALUES(?,?,?,?,?,?)',
                   (1, 'ENTRADA', 'movements', identifier,
                    '{"source_type":"NOTA_FISCAL","source_reference":"NF-TEST","password_hash":"PRIVATE"}', '2026-01-01T00:00:00+00:00'))
    movements = report(admin, 'movements')['rows']
    assert movements[0]['purpose'] == 'EMPRESTIMO'
    assert movements[1]['source_type'] == 'NOTA_FISCAL'
    assert movements[1]['source_reference'] == 'NF-TEST'
    assert 'PRIVATE' not in str(movements)
    assert report(admin, 'movements', source_type='NOTA_FISCAL')['rows'][0]['id'] == identifier


def test_explicit_legacy_consumption_responsible_remains_distinct_from_loans(admin, catalog):
    move(admin, catalog, 'ENTRADA', '1.000')
    consumed = move(admin, catalog, 'SAIDA', '0.125', purpose='CONSUMO')
    move(admin, catalog, 'SAIDA', '0.125', purpose='EMPRESTIMO')
    assert [row['id'] for row in report(admin, 'movements', purpose='CONSUMO')['rows']] == [consumed]
    assert len(report(admin, 'loans')['rows']) == 1
    assert report(admin, 'stock', material_id=catalog['material']['id'])['rows'][0]['borrowed'] == '0.125'


def test_large_export_fails_explicitly_instead_of_truncating(admin, catalog, monkeypatch):
    move(admin, catalog, 'ENTRADA', '0.001')
    move(admin, catalog, 'ENTRADA', '0.001')
    monkeypatch.setattr('app.reporting.MAX_REPORT_ROWS', 1)
    response = admin.get('/api/reports/movements/export')
    assert response.status_code == 413
    assert 'nenhum registro' in response.json()['detail']


def test_direct_reader_preserves_available_and_borrowed_exactly(admin, catalog):
    move(admin, catalog, 'ENTRADA', '1.000')
    move(admin, catalog, 'SAIDA', '0.001')
    with connect(write=True) as db:
        db.execute('UPDATE balances SET quantity=? WHERE material_id=?', (9007199254740993, catalog['material']['id']))
    with connect(snapshot=True) as db:
        data = get_report(db, 'stock', {'material_id': str(catalog['material']['id'])})
    assert data['rows'][0]['available'] == '9007199254740.993'
    assert data['rows'][0]['total_control'] == '9007199254740.994'
