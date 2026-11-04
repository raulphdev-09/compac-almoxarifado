"""Stock integrity checks against disposable SQLite/PostgreSQL fixtures."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app import main
from app.db import Database, connect
from conftest import ADMIN_PASSWORD
from test_workflows import catalog_input, movement, successful


def payload(catalog, kind='ENTRADA', quantity=1):
    data = {'type': kind, 'material_id': catalog['material']['id'], 'quantity': quantity}
    if kind in ('ENTRADA', 'DEVOLUCAO', 'TRANSFERENCIA', 'AJUSTE'):
        data['destination_id'] = catalog['destination' if kind == 'TRANSFERENCIA' else 'origin']['id']
    if kind in ('SAIDA', 'TRANSFERENCIA'):
        data['origin_id'] = catalog['origin']['id']
    if kind in ('SAIDA', 'DEVOLUCAO'):
        data['employee_id'] = catalog['employee']['id']
    if kind == 'AJUSTE':
        data['notes'] = 'Conferência fictícia de teste'
    return data


def post(client, data, key):
    headers = {} if key is None else {'Idempotency-Key': key}
    return client.post('/api/movements', json=data, headers=headers)


def snapshot():
    with connect() as db:
        return {
            table: [dict(row) for row in db.execute(f'SELECT * FROM {table}')]
            for table in ('materials', 'balances', 'movements', 'loans', 'audit', 'idempotency_requests')
        }


@pytest.mark.parametrize('key', [None, '', 'has space', ' leading', 'bad/key', 'x' * 129, '.starts-with-symbol'])
def test_movements_require_valid_idempotency_key(admin, catalog, key):
    before = snapshot()
    response = post(admin, payload(catalog), key)
    assert response.status_code == 422
    assert snapshot() == before


@pytest.mark.parametrize('key', ['x', 'x' * 128, 'stock:batch_01.a-b'])
def test_idempotency_key_accepts_documented_bounds(admin, catalog, key):
    assert post(admin, payload(catalog), key).status_code == 201


@pytest.mark.parametrize('kind', ['ENTRADA', 'SAIDA', 'DEVOLUCAO', 'TRANSFERENCIA', 'AJUSTE'])
def test_movement_replay_preserves_stock_loans_and_audit(admin, catalog, kind):
    if kind != 'ENTRADA':
        successful(movement(admin, catalog, 'ENTRADA', 5))
    if kind == 'DEVOLUCAO':
        successful(movement(admin, catalog, 'SAIDA', 2))
    data = payload(catalog, kind)
    key = str(uuid.uuid4())
    first = post(admin, data, key)
    assert first.status_code == 201, first.text
    committed = snapshot()
    # Reordered JSON keys represent the same payload.
    second = post(admin, dict(reversed(list(data.items()))), key)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert snapshot() == committed


def test_reusing_key_with_changed_payload_is_conflict(admin, catalog):
    key = str(uuid.uuid4())
    assert post(admin, payload(catalog), key).status_code == 201
    committed = snapshot()
    conflict = post(admin, payload(catalog, quantity=2), key)
    assert conflict.status_code == 409
    assert snapshot() == committed


def test_idempotency_is_scoped_to_authenticated_user(admin, catalog, client_factory):
    operator = successful(admin.post('/api/users', json={
        'name': 'Operador fictício', 'username': 'operator_integrity',
        'password': ADMIN_PASSWORD, 'role': 'OPERADOR',
    }))
    key = str(uuid.uuid4())
    first = successful(post(admin, payload(catalog), key))
    session = client_factory()
    successful(session.post('/api/auth/login', json={
        'username': 'operator_integrity', 'password': ADMIN_PASSWORD,
    }))
    second = successful(post(session, payload(catalog), key))
    assert second['id'] != first['id']
    records = snapshot()
    assert len(records['movements']) == 2
    assert sum(row['quantity'] for row in records['balances']) == 2000
    assert {row['user_id'] for row in records['idempotency_requests']} == {1, operator['id']}


def test_concurrent_identical_requests_commit_one_movement(admin, catalog, client_factory):
    sessions = [client_factory(), client_factory()]
    for session in sessions:
        successful(session.post('/api/auth/login', json={
            'username': 'admin', 'password': ADMIN_PASSWORD,
        }))
    barrier = Barrier(2)
    key = str(uuid.uuid4())
    data = payload(catalog)

    def submit(session):
        barrier.wait(timeout=10)
        return post(session, data, key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(submit, sessions))
    assert [reply.status_code for reply in replies] == [201, 201]
    assert replies[0].json() == replies[1].json()
    result = snapshot()
    assert len(result['movements']) == 1
    assert len(result['idempotency_requests']) == 1
    assert sum(row['quantity'] for row in result['balances']) == 1000
    assert len([row for row in result['audit'] if row['entity'] == 'movements']) == 1


@pytest.mark.parametrize('failure', ['audit', 'idempotency_insert'])
def test_failed_operation_rolls_back_stock_audit_and_key(admin, catalog, monkeypatch, failure):
    before = snapshot()
    key = str(uuid.uuid4())

    def fail_audit(*args, **kwargs):
        raise RuntimeError('integrity-injected-failure')

    execute = Database.execute

    def fail_key_insert(db, sql, params=()):
        if sql.startswith('INSERT INTO idempotency_requests'):
            raise RuntimeError('integrity-injected-failure')
        return execute(db, sql, params)

    with monkeypatch.context() as patch:
        if failure == 'audit':
            patch.setattr(main, 'audit', fail_audit)
        else:
            patch.setattr(Database, 'execute', fail_key_insert)
        with pytest.raises(RuntimeError, match='integrity-injected-failure'):
            post(admin, payload(catalog), key)
    assert snapshot() == before
    # A failed transaction must not consume the request key.
    assert post(admin, payload(catalog), key).status_code == 201
    assert len(snapshot()['movements']) == 1


def test_business_validation_failure_does_not_consume_key(admin, catalog):
    key = str(uuid.uuid4())
    data = payload(catalog, 'SAIDA')
    assert post(admin, data, key).status_code == 409
    assert snapshot()['idempotency_requests'] == []
    successful(movement(admin, catalog, 'ENTRADA', 2))
    assert post(admin, data, key).status_code == 201


def test_material_without_history_can_change_unit_and_asset_mode(admin, catalog):
    record = catalog['material']
    reply = admin.put(f"/api/catalog/materials/{record['id']}", json=catalog_input(record, unit='KG', individualizable=True))
    assert reply.status_code == 200
    assert reply.json()['unit'] == 'KG'
    assert reply.json()['individualizable'] == 1


@pytest.mark.parametrize('history', ['zero_balance', 'movements', 'closed_loan', 'equipment', 'requisition', 'expense', 'consumption_profile'])
@pytest.mark.parametrize('field', ['unit', 'individualizable'])
def test_material_identity_is_immutable_with_operational_links(admin, catalog, history, field):
    record = catalog['material']
    material_id = record['id']
    if history == 'zero_balance':
        with connect(write=True) as db:
            db.execute('INSERT INTO balances(material_id,location_id,quantity) VALUES(?,?,0)', (material_id, catalog['origin']['id']))
    elif history == 'movements':
        successful(movement(admin, catalog, 'ENTRADA', 1))
        successful(movement(admin, catalog, 'SAIDA', 1, employee_id=None))
    elif history == 'closed_loan':
        successful(movement(admin, catalog, 'ENTRADA', 1))
        successful(movement(admin, catalog, 'SAIDA', 1))
        successful(movement(admin, catalog, 'DEVOLUCAO', 1))
    elif history == 'equipment':
        record = successful(admin.put(f'/api/catalog/materials/{material_id}', json=catalog_input(record, individualizable=True)))
        successful(admin.post('/api/catalog/equipment', json={
            'asset_tag': 'INTEGRITY-ASSET', 'material_id': material_id,
            'location_id': catalog['origin']['id'], 'condition': 'BOA', 'status': 'DISPONIVEL',
        }))
    elif history == 'requisition':
        successful(admin.post('/api/requisitions', json={
            'work_id': catalog['work']['id'], 'priority': 'NORMAL',
            'items': [{'material_id': material_id, 'quantity': 1}],
        }))
    elif history == 'expense':
        successful(admin.post('/api/catalog/expenses', json={
            'supplier': 'Fornecedor fictício', 'purchase_date': '2026-11-04',
            'material_id': material_id, 'quantity': 1, 'unit_cost': 2,
        }))
    elif history == 'consumption_profile':
        successful(admin.post('/api/catalog/consumption_profiles', json={
            'work_id': catalog['work']['id'], 'activity': 'Atividade fictícia',
            'material_id': material_id, 'consumption_per_unit': 1,
        }))
    before = snapshot()
    change = {'unit': 'KG'} if field == 'unit' else {'individualizable': not bool(record['individualizable'])}
    response = admin.put(f'/api/catalog/materials/{material_id}', json=catalog_input(record, **change))
    assert response.status_code == 409, response.text
    assert snapshot() == before
    # Description and status remain editable without changing existing stock.
    response = admin.put(f'/api/catalog/materials/{material_id}', json=catalog_input(record, description='Descrição revisada', status='INATIVO'))
    assert response.status_code == 200
    after = snapshot()
    for table in ('balances', 'loans', 'movements'):
        assert after[table] == before[table]
