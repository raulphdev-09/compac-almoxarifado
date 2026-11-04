"""Observes current stock behavior in a generated SQLite DB or explicit local audit schema."""
import json
import os
import sys
if sys.flags.optimize:
    raise RuntimeError('Audit scripts require assertions; run Python without -O')
import tempfile
import uuid
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import quote

import psycopg
from psycopg import sql as pgsql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in ('DATABASE_URL', 'COMPAC_REQUIRE_POSTGRES', 'RENDER', 'COMPAC_SETUP_TOKEN', 'COMPAC_PUBLIC_URL', 'RENDER_EXTERNAL_URL'):
    os.environ.pop(name, None)
os.environ['COMPAC_COOKIE_SECURE'] = '0'

from fastapi.testclient import TestClient
from app import main
from app.db import connect

results = {}

@contextmanager
def audit_database():
    pg_url = os.environ.get('COMPAC_OPERATION_AUDIT_PG_URL')
    if pg_url:
        # Explicit disposable database supplied by the audit coordinator only.
        if pg_url != 'postgresql://compac_audit@127.0.0.1:55439/compac_audit':
            raise ValueError('Only the disposable local audit database is allowed')
        schema = 'operations_' + uuid.uuid4().hex
        with psycopg.connect(pg_url, autocommit=True) as db:
            db.execute(pgsql.SQL('CREATE SCHEMA {}').format(pgsql.Identifier(schema)))
        os.environ['DATABASE_URL'] = pg_url + '?options=' + quote('-c search_path=' + schema)
        try:
            yield None
        finally:
            os.environ.pop('DATABASE_URL', None)
            with psycopg.connect(pg_url, autocommit=True) as db:
                db.execute(pgsql.SQL('DROP SCHEMA {} CASCADE').format(pgsql.Identifier(schema)))
    else:
        with tempfile.TemporaryDirectory(prefix='compac-operation-audit-') as temporary:
            os.environ['COMPAC_DB'] = temporary + '/audit.db'
            yield temporary

with audit_database() as temporary:
    with TestClient(main.app, headers={'X-Compac-Client': 'web'}, raise_server_exceptions=False) as client:
        def post(path, body):
            response = client.post(path, json=body)
            assert response.is_success, (path, response.status_code, response.text)
            return response.json()

        def create(entity, **body):
            return post('/api/catalog/' + entity, body)

        def sql(statement):
            with connect() as db:
                return [dict(row) for row in db.execute(statement)]

        post('/api/auth/setup', {'name': 'Audit Admin', 'username': 'audit', 'password': 'Audit-Temporary-Password'})
        category = create('categories', name='Categoria fictícia')
        work = create('works', code='AUDIT', name='Obra fictícia', status='ATIVA')
        location = create('locations', name='Local fictício', work_id=work['id'])
        employee = create('employees', registration='AUDIT01', name='Pessoa fictícia', job_title='Teste', work_id=work['id'], status='ATIVO')
        data = {'code':'AUDIT-1', 'description':'Ferramenta fictícia', 'category_id':category['id'], 'unit':'UN', 'minimum_stock':0, 'individualizable':True, 'status':'ATIVO'}
        material = create('materials', **data)
        results['zero_on_catalog_create'] = client.get('/api/stock').json()
        results['initial_quantity_field'] = client.post('/api/catalog/materials', json={**data, 'code':'AUDIT-INITIAL', 'initial_quantity': 2, 'location_id': location['id']}).status_code
        results['duplicate_code_case_insensitive'] = client.post('/api/catalog/materials', json={**data, 'code':'audit-1'}).status_code

        movement = {'type':'ENTRADA', 'material_id':material['id'], 'quantity':2, 'destination_id':location['id'], 'notes':'Recebimento fictício'}
        first = client.post('/api/movements', json=movement, headers={'Idempotency-Key': 'audit-same-request'})
        repeated = client.post('/api/movements', json=movement, headers={'Idempotency-Key': 'audit-same-request'})
        assert first.status_code == repeated.status_code == 201
        assert first.json()['id'] != repeated.json()['id']
        results['repeated_movement'] = {'statuses':[first.status_code, repeated.status_code], 'movement_ids':[first.json()['id'],repeated.json()['id']], 'available':client.get('/api/stock').json()[0]['quantity']}

        results['negative_movement_status'] = client.post('/api/movements', json={**movement, 'quantity':-1}).status_code
        results['zero_entry_status'] = client.post('/api/movements', json={**movement, 'quantity':0}).status_code
        results['catalog_balance_field_status'] = client.put('/api/catalog/materials/' + str(material['id']), json={**data, 'quantity':500}).status_code

        changed = client.put('/api/catalog/materials/' + str(material['id']), json={**data, 'unit':'KG'})
        assert changed.status_code == 200
        results['edit_material_unit'] = {'status':changed.status_code, 'stock':client.get('/api/stock').json(), 'historical_movement_units':[row['unit'] for row in client.get('/api/movements').json()]}

        before = client.get('/api/stock').json()
        create('expenses', supplier='Fornecedor fictício', document_number='NF-AUDIT', purchase_date='2026-11-04', material_id=material['id'], work_id=work['id'], quantity=3, unit_cost=25)
        results['expense_does_not_receive_stock'] = {'before':before[0]['quantity'], 'after':client.get('/api/stock').json()[0]['quantity'], 'movements':len(client.get('/api/movements').json())}

        post('/api/movements', {'type':'SAIDA', 'material_id':material['id'], 'quantity':1, 'origin_id':location['id'], 'employee_id':employee['id']})
        post('/api/movements', {'type':'DEVOLUCAO', 'material_id':material['id'], 'quantity':0.25, 'destination_id':location['id'], 'employee_id':employee['id']})
        results['loan_return'] = {'available':client.get('/api/stock').json()[0]['quantity'], 'outstanding':sum(row['quantity'] for row in client.get('/api/loans').json())}

        state = lambda: {'stock':client.get('/api/stock').json(), 'movements':client.get('/api/movements').json(), 'loans':client.get('/api/loans').json(), 'audit_count':sql('SELECT COUNT(*) AS count FROM audit')[0]['count']}
        before_failure = state()
        with patch.object(main, 'audit', side_effect=RuntimeError('AUDIT_INJECTED_FAILURE')):
            failed = client.post('/api/movements', json=movement)
        after_failure = state()
        results['rollback_injected_audit_failure'] = {'status':failed.status_code, 'state_unchanged':before_failure == after_failure}
        assert failed.status_code == 500 and before_failure == after_failure

print(json.dumps(results, indent=2, ensure_ascii=False))
