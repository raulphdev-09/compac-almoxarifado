"""Imports must be reviewable, traceable, atomic and safe to retry."""

import base64
from contextlib import contextmanager
import csv
import io
import json
import uuid

import pytest

from app.db import connect
from conftest import ADMIN_PASSWORD


MATERIAL_COLUMNS = ['codigo', 'descricao', 'categoria', 'unidade', 'minimo', 'saldo_inicial', 'local', 'tipo_origem', 'referencia']
MOVEMENT_COLUMNS = ['tipo', 'codigo_material', 'quantidade', 'origem', 'destino', 'matricula', 'finalidade', 'tipo_origem', 'referencia', 'observacoes']
TABLES = ('users', 'sessions', 'materials', 'balances', 'movements', 'loans', 'audit', 'idempotency_requests')


def successful(response):
    assert response.is_success, response.text
    return response.json()


def upload(columns, rows, filename='importacao.csv'):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns, delimiter=';')
    writer.writeheader()
    writer.writerows(rows)
    return {'filename': filename, 'content_base64': base64.b64encode(stream.getvalue().encode('utf-8-sig')).decode()}


def material(code='NOVO-01', **extra):
    return {
        'codigo': code, 'descricao': 'Cimento de teste', 'categoria': 'Materiais gerais',
        'unidade': 'KG', 'minimo': '1,125', **extra,
    }


def incoming(code='MAT-001', amount='5.125'):
    return {
        'tipo': 'ENTRADA', 'codigo_material': code, 'quantidade': amount,
        'destino': 'Almoxarifado', 'tipo_origem': 'NOTA_FISCAL', 'referencia': 'NF-2026-01',
    }


def preview(client, entity, body):
    return successful(client.post(f'/api/import/{entity}/preview', json=body))


def confirm(client, entity, body, reviewed, key=None):
    return client.post(
        f'/api/import/{entity}/confirm', json={**body, 'preview_token': reviewed['preview_token']},
        headers={'Idempotency-Key': key or str(uuid.uuid4())},
    )


def snapshot():
    with connect() as db:
        return {
            table: sorted(json.dumps(dict(row), sort_keys=True, default=str) for row in db.execute(f'SELECT * FROM {table}'))
            for table in TABLES
        }


def test_material_preview_has_no_effects_and_initial_stock_is_traced_entry(admin, catalog):
    body = upload(MATERIAL_COLUMNS, [material(
        saldo_inicial='12.345', local='Almoxarifado', tipo_origem='INVENTARIO_INICIAL',
    )])
    before = snapshot()
    reviewed = preview(admin, 'materials', body)
    assert reviewed['errors'] == []
    assert reviewed['valid_rows'] == 1
    assert reviewed['preview_token']
    assert reviewed['expires_at']
    assert snapshot() == before, 'Preview must roll back materials, audit, movements and balances.'

    key = str(uuid.uuid4())
    first = successful(confirm(admin, 'materials', body, reviewed, key))
    assert first['imported_rows'] == 1
    assert len(first['material_ids']) == len(first['movement_ids']) == 1
    with connect() as db:
        saved = db.execute('SELECT * FROM materials WHERE code=?', ('NOVO-01',)).fetchone()
        assert saved['minimum_stock'] == 1.125
        assert db.execute('SELECT quantity FROM balances WHERE material_id=?', (saved['id'],)).fetchone()['quantity'] == 12345
        movement = db.execute('SELECT * FROM movements WHERE id=?', (first['movement_ids'][0],)).fetchone()
        assert movement['type'] == 'ENTRADA'
        assert first['batch_id'] in movement['notes']
        assert 'importacao.csv' in movement['notes']
        assert 'linha 2' in movement['notes']
        audit = db.execute("SELECT details FROM audit WHERE entity='movements' AND record_id=?", (movement['id'],)).fetchone()
        assert json.loads(audit['details'])['source_type'] == 'INVENTARIO_INICIAL'
    after = snapshot()
    assert successful(confirm(admin, 'materials', body, reviewed, key)) == first
    assert snapshot() == after
    assert successful(confirm(admin, 'materials', body, reviewed)) == first
    later = snapshot()
    for table in TABLES:
        if table != 'idempotency_requests':
            assert later[table] == after[table], 'Changing Idempotency-Key must never execute the token twice.'


def test_confirmation_rechecks_live_catalog_and_rolls_back_entire_batch(admin, catalog):
    body = upload(MATERIAL_COLUMNS, [
        material('NOVO-A', saldo_inicial='3', local='Almoxarifado', tipo_origem='NOTA_FISCAL', referencia='NF-A'),
        material('NOVO-B', saldo_inicial='4', local='Almoxarifado', tipo_origem='NOTA_FISCAL', referencia='NF-B'),
    ])
    reviewed = preview(admin, 'materials', body)
    assert not reviewed['errors']
    catalog['create'](
        'materials', code='NOVO-B', description='Cadastro concorrente',
        category_id=catalog['category']['id'], unit='KG', minimum_stock=0,
        individualizable=False, status='ATIVO',
    )
    before = snapshot()
    response = confirm(admin, 'materials', body, reviewed)
    assert response.status_code == 422, response.text
    assert response.json()['detail']['errors'][0]['row'] == 3
    assert snapshot() == before, 'Even the valid first material and its entry must be rolled back.'


def test_movements_preview_uses_real_sequential_balance_rules_and_preserves_purpose(admin, catalog):
    successful(admin.post('/api/movements', json={
        'type': 'ENTRADA', 'material_id': catalog['material']['id'], 'quantity': 10,
        'destination_id': catalog['origin']['id'],
    }, headers={'Idempotency-Key': str(uuid.uuid4())}))
    body = upload(MOVEMENT_COLUMNS, [
        {'tipo': 'SAIDA', 'codigo_material': 'MAT-001', 'quantidade': '2', 'origem': 'Almoxarifado', 'matricula': 'MAT-001', 'finalidade': 'CONSUMO'},
        {'tipo': 'SAIDA', 'codigo_material': 'MAT-001', 'quantidade': '3', 'origem': 'Almoxarifado', 'matricula': 'MAT-001', 'finalidade': 'EMPRESTIMO'},
        {'tipo': 'DEVOLUCAO', 'codigo_material': 'MAT-001', 'quantidade': '1', 'destino': 'Almoxarifado', 'matricula': 'MAT-001'},
        {'tipo': 'TRANSFERENCIA', 'codigo_material': 'MAT-001', 'quantidade': '1', 'origem': 'Almoxarifado', 'destino': 'Frente de serviço'},
    ])
    before = snapshot()
    reviewed = preview(admin, 'movements', body)
    assert reviewed['errors'] == []
    assert any('FIFO' in warning['message'] and warning['row'] == 4 for warning in reviewed['warnings'])
    assert snapshot() == before, 'The simulated loan and its return must disappear after preview.'
    result = successful(confirm(admin, 'movements', body, reviewed))
    assert result['imported_rows'] == 4
    with connect() as db:
        loans = db.execute('SELECT * FROM loans').fetchall()
        assert len(loans) == 1, 'Consumption with a responsible employee must not create an implicit loan.'
        assert loans[0]['quantity'] == 2000
        balances = {row['location_id']: row['quantity'] for row in db.execute('SELECT * FROM balances WHERE material_id=?', (catalog['material']['id'],))}
        assert balances[catalog['origin']['id']] == 5000
        assert balances[catalog['destination']['id']] == 1000


def test_new_entry_then_consumption_in_same_import_is_valid_without_preview_effects(admin, catalog):
    body = upload(MOVEMENT_COLUMNS, [
        incoming(),
        {'tipo': 'SAIDA', 'codigo_material': 'MAT-001', 'quantidade': '1,125', 'origem': 'Almoxarifado', 'finalidade': 'CONSUMO'},
    ])
    before = snapshot()
    reviewed = preview(admin, 'movements', body)
    assert reviewed['errors'] == []
    assert snapshot() == before
    successful(confirm(admin, 'movements', body, reviewed))
    with connect() as db:
        assert db.execute('SELECT quantity FROM balances WHERE material_id=?', (catalog['material']['id'],)).fetchone()['quantity'] == 4000


@pytest.mark.parametrize('row,message', [
    (incoming(amount='-1'), 'negativo'),
    (incoming(amount='1.0001'), '3 casas'),
    (incoming(amount='NaN'), 'número'),
    (incoming(amount='0'), 'maior que zero'),
    ({**incoming(), 'referencia': ''}, 'referencia'),
    ({**incoming(), 'tipo': 'AJUSTE', 'tipo_origem': '', 'referencia': ''}, 'Ajustes'),
    ({'tipo': 'SAIDA', 'codigo_material': 'MAT-001', 'quantidade': '1', 'origem': 'Almoxarifado', 'matricula': 'MAT-001'}, 'finalidade'),
])
def test_preview_reports_safe_line_errors_and_has_no_token(admin, catalog, row, message):
    before = snapshot()
    reviewed = preview(admin, 'movements', upload(MOVEMENT_COLUMNS, [row]))
    assert reviewed['preview_token'] is None
    assert reviewed['errors'][0]['row'] == 2
    assert message in reviewed['errors'][0]['message']
    assert snapshot() == before


def test_duplicate_rows_and_existing_material_cannot_overwrite_inventory(admin, catalog):
    before = snapshot()
    reviewed = preview(admin, 'materials', upload(MATERIAL_COLUMNS, [material('MAT-001')]))
    assert 'já cadastrado' in reviewed['errors'][0]['message']
    assert snapshot() == before
    reviewed = preview(admin, 'movements', upload(MOVEMENT_COLUMNS, [incoming(), incoming()]))
    assert reviewed['errors'][0]['row'] == 3
    assert 'duplicada' in reviewed['errors'][0]['message']
    assert snapshot() == before


@pytest.mark.parametrize('headers', [
    ['codigo', 'Código', 'descricao', 'categoria', 'unidade'],
    ['codigo', 'descricao', 'categoria', 'unidade', 'created_at'],
    ['codigo', 'descricao', 'categoria', 'unidade', 'saldo'],
])
def test_duplicate_or_forbidden_headers_are_rejected_before_effects(admin, catalog, headers):
    before = snapshot()
    body = upload(headers, [dict.fromkeys(headers, 'teste')])
    response = admin.post('/api/import/materials/preview', json=body)
    assert response.status_code == 422, response.text
    assert snapshot() == before


def test_signed_preview_is_bound_to_actor_entity_exact_file_and_expiry(admin, catalog, client_factory, monkeypatch):
    from app import import_workflows

    body = upload(MATERIAL_COLUMNS, [material()])
    reviewed = preview(admin, 'materials', body)
    before = snapshot()
    changed = upload(MATERIAL_COLUMNS, [material(descricao='Conteúdo alterado')])
    assert confirm(admin, 'materials', changed, reviewed).status_code == 409
    assert confirm(admin, 'movements', body, reviewed).status_code == 409
    assert confirm(admin, 'materials', body, {'preview_token': reviewed['preview_token'] + 'x'}).status_code == 409
    assert snapshot() == before

    successful(admin.post('/api/users', json={'name': 'Operador', 'username': 'operador-import', 'role': 'OPERADOR', 'password': ADMIN_PASSWORD}))
    other = client_factory()
    successful(other.post('/api/auth/login', json={'username': 'operador-import', 'password': ADMIN_PASSWORD}))
    after_user = snapshot()
    assert confirm(other, 'materials', body, reviewed).status_code == 409
    assert snapshot() == after_user

    clock = import_workflows.time.time()
    monkeypatch.setattr(import_workflows.time, 'time', lambda: clock + 901)
    assert confirm(admin, 'materials', body, reviewed).status_code == 409
    assert snapshot() == after_user


@pytest.mark.parametrize('state,status', [('session_removed', 401), ('inactive', 401), ('consultation', 403)])
@pytest.mark.parametrize('replay', [False, True])
def test_revocation_is_checked_inside_writer_before_any_confirmation_or_replay(admin, catalog, monkeypatch, state, status, replay):
    from app import main

    body = upload(MOVEMENT_COLUMNS, [incoming()])
    reviewed = preview(admin, 'movements', body)
    key = str(uuid.uuid4())
    if replay:
        successful(confirm(admin, 'movements', body, reviewed, key))
    actor = successful(admin.get('/api/auth/me'))
    observed = {'baseline': None, 'writers': 0}

    @contextmanager
    def revoke_before_writer(write=False):
        if write:
            observed['writers'] += 1
            if observed['baseline'] is None:
                with connect(write=True) as db:
                    if state == 'session_removed':
                        db.execute('DELETE FROM sessions WHERE user_id=?', (actor['id'],))
                    elif state == 'inactive':
                        db.execute('UPDATE users SET active=0 WHERE id=?', (actor['id'],))
                    else:
                        db.execute("UPDATE users SET role='CONSULTA' WHERE id=?", (actor['id'],))
                observed['baseline'] = snapshot()
        with connect(write=write) as db:
            yield db

    monkeypatch.setattr(main, 'connect', revoke_before_writer)
    response = confirm(admin, 'movements', body, reviewed, key)
    assert observed['writers'] == 1
    assert response.status_code == status, response.text
    assert snapshot() == observed['baseline']


def test_same_idempotency_key_cannot_confirm_a_different_reviewed_file(admin, catalog):
    body = upload(MOVEMENT_COLUMNS, [incoming()])
    reviewed = preview(admin, 'movements', body)
    key = str(uuid.uuid4())
    successful(confirm(admin, 'movements', body, reviewed, key))
    other_body = upload(MOVEMENT_COLUMNS, [incoming(amount='8')])
    other_reviewed = preview(admin, 'movements', other_body)
    before = snapshot()
    response = confirm(admin, 'movements', other_body, other_reviewed, key)
    assert response.status_code == 409, response.text
    assert snapshot() == before


@pytest.mark.parametrize('entity', ['stock', 'dashboard', 'balances', 'users', 'loans'])
def test_derived_views_and_other_entities_are_not_importable(admin, catalog, entity):
    response = admin.post(f'/api/import/{entity}/preview', json=upload(MATERIAL_COLUMNS, [material()]))
    assert response.status_code == 404
    assert admin.get(f'/api/import/{entity}/template').status_code == 404


@pytest.mark.parametrize('format', ['csv', 'xlsx'])
@pytest.mark.parametrize('entity,expected', [('materials', MATERIAL_COLUMNS), ('movements', MOVEMENT_COLUMNS)])
def test_download_templates_contain_exact_importable_headers(admin, entity, expected, format):
    from app.document_formats import parse_table

    response = admin.get(f'/api/import/{entity}/template?format={format}')
    assert response.status_code == 200, response.text
    assert f'modelo-{entity}.{format}' in response.headers['content-disposition']
    assert response.headers['cache-control'] == 'no-store'
    headers, rows = parse_table(response.content, f'modelo.{format}')
    assert headers == expected
    assert rows == []


def test_rejects_invalid_base64_oversize_upload_and_unsafe_spreadsheet(admin, catalog):
    from openpyxl import Workbook

    before = snapshot()
    assert admin.post('/api/import/materials/preview', json={'filename': 'x.csv', 'content_base64': '???'}).status_code == 422
    assert admin.post('/api/import/materials/preview', json={'filename': 'x.csv', 'content_base64': 'A' * (3 * 1024 * 1024)}).status_code == 413
    book = Workbook()
    sheet = book.active
    sheet.append(MATERIAL_COLUMNS)
    sheet.append(['=1+1', 'Material', 'Materiais gerais', 'UN'])
    stream = io.BytesIO()
    book.save(stream)
    response = admin.post('/api/import/materials/preview', json={'filename': 'unsafe.xlsx', 'content_base64': base64.b64encode(stream.getvalue()).decode()})
    assert response.status_code == 422
    assert snapshot() == before


def test_unicode_filename_can_be_confirmed_with_its_signed_preview(admin, catalog):
    body = upload(MATERIAL_COLUMNS, [material()], filename='😀' * 170 + '.csv')
    reviewed = preview(admin, 'materials', body)
    assert reviewed['preview_token']
    assert len(reviewed['preview_token']) <= 2048
    assert successful(confirm(admin, 'materials', body, reviewed))['imported_rows'] == 1


@pytest.mark.parametrize('format', ['csv', 'xlsx'])
def test_preview_errors_use_original_file_row_numbers(admin, catalog, format):
    if format == 'csv':
        body = upload(MOVEMENT_COLUMNS, [incoming(amount='-1')])
        text = base64.b64decode(body['content_base64']).decode('utf-8-sig')
        header, row = text.splitlines()
        body['content_base64'] = base64.b64encode(('\n\n' + header + '\n\n' + row + '\n').encode()).decode()
        expected = 5
    else:
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        for index, value in enumerate(MOVEMENT_COLUMNS, 1):
            sheet.cell(3, index, value)
            sheet.cell(10, index, incoming(amount='-1').get(value, ''))
        stream = io.BytesIO()
        book.save(stream)
        body = {'filename': 'linhas.xlsx', 'content_base64': base64.b64encode(stream.getvalue()).decode()}
        expected = 10
    before = snapshot()
    reviewed = preview(admin, 'movements', body)
    assert reviewed['errors'][0]['row'] == expected
    assert reviewed['rows'][0]['row'] == expected
    assert snapshot() == before


def test_movement_provenance_keeps_original_csv_row_number(admin, catalog):
    body = upload(MOVEMENT_COLUMNS, [incoming()])
    text = base64.b64decode(body['content_base64']).decode('utf-8-sig')
    header, row = text.splitlines()
    body['content_base64'] = base64.b64encode(('\n\n' + header + '\n\n' + row + '\n').encode()).decode()
    reviewed = preview(admin, 'movements', body)
    assert reviewed['rows'][0]['row'] == 5
    result = successful(confirm(admin, 'movements', body, reviewed))
    with connect() as db:
        notes = db.execute('SELECT notes FROM movements WHERE id=?', (result['movement_ids'][0],)).fetchone()['notes']
        assert 'linha 5.' in notes
