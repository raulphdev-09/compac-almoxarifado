"""Revocation must take effect before protected transaction effects or replay.

The hook commits a concurrent administrator's change after Depends has accepted
the request, but immediately before the endpoint acquires its writer lock. No
timing assumptions, threads, employee photos, or production databases are used.
"""
from contextlib import contextmanager
import json
import re
import uuid

import pytest

from app.db import connect
from conftest import ADMIN_PASSWORD


WRITERS = (
    'create_user', 'edit_user', 'create_catalog', 'update_catalog',
    'new_movement', 'replayed_movement', 'create_requisition',
    'approve_requisition', 'create_ticket', 'comment_ticket', 'update_ticket',
    'open_maintenance', 'close_maintenance',
)
REVOCATIONS = ('session_removed', 'inactive', 'consultation_only')


def successful(response):
    assert response.is_success, f'{response.status_code}: {response.text}'
    return response.json()


def snapshot():
    """Include every business, credential, audit and idempotency row.

    The baseline is captured *after* the deliberate revocation commits, so even
    a change to a target user or an unexpected audit record makes it differ.
    """
    with connect() as db:
        if db.postgres:
            tables = [row['table_name'] for row in db.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=current_schema() AND table_type='BASE TABLE'",
            )]
        else:
            tables = [row['name'] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
            )]
        result = {}
        for table in sorted(tables):
            assert re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*', table)
            result[table] = sorted(
                json.dumps(dict(row), sort_keys=True, default=str)
                for row in db.execute(f'SELECT * FROM {table}')
            )
        return result


def revoke(actor_id, state):
    with connect(write=True) as db:
        if state == 'session_removed':
            db.execute('DELETE FROM sessions WHERE user_id=?', (actor_id,))
        elif state == 'session_expired':
            db.execute("UPDATE sessions SET expires_at='1970-01-01T00:00:00+00:00' WHERE user_id=?", (actor_id,))
        elif state == 'inactive':
            db.execute('UPDATE users SET active=0 WHERE id=?', (actor_id,))
        else:
            role = 'CONSULTA' if state == 'consultation_only' else 'OPERADOR'
            assert state in ('consultation_only', 'operator_only')
            # Keep the original session: a fresh lookup of role is necessary,
            # even when no external session deletion accompanied demotion.
            db.execute('UPDATE users SET role=? WHERE id=?', (role, actor_id))


def race_before_writer(monkeypatch, actor_id, state):
    from app import main

    observed = {'writers': 0, 'baseline': None}

    @contextmanager
    def guarded_connect(write=False):
        if write:
            observed['writers'] += 1
            if observed['baseline'] is None:
                revoke(actor_id, state)
                observed['baseline'] = snapshot()
        with connect(write=write) as db:
            yield db

    monkeypatch.setattr(main, 'connect', guarded_connect)
    return observed


def movement(catalog, kind='ENTRADA'):
    return {
        'type': kind, 'material_id': catalog['material']['id'], 'quantity': 5,
        'destination_id': catalog['origin']['id'],
        'notes': 'Conferência supervisionada de teste',
    }


def request_for(writer, admin, catalog):
    """Prepare valid requests before inserting a revocation race."""
    headers = {}
    if writer in ('create_user', 'edit_user'):
        path = '/api/users'
        body = {'name': 'Usuário de teste', 'username': 'worker', 'role': 'ADMIN', 'password': ADMIN_PASSWORD}
        if writer == 'edit_user':
            target = successful(admin.post(path, json={**body, 'role': 'OPERADOR'}))
            return 'PATCH', f"{path}/{target['id']}", {'role': 'ADMIN'}, headers
        return 'POST', path, body, headers
    if writer == 'create_catalog':
        return 'POST', '/api/catalog/categories', {'name': 'Nova categoria', 'description': 'Teste'}, headers
    if writer == 'update_catalog':
        return 'PUT', f"/api/catalog/categories/{catalog['category']['id']}", {
            'name': 'Categoria revisada', 'description': 'Atualização testada',
        }, headers
    if writer in ('new_movement', 'replayed_movement', 'new_adjustment', 'replayed_adjustment'):
        body = movement(catalog, 'AJUSTE' if 'adjustment' in writer else 'ENTRADA')
        headers = {'Idempotency-Key': str(uuid.uuid4())}
        if writer.startswith('replayed_'):
            successful(admin.post('/api/movements', json=body, headers=headers))
        return 'POST', '/api/movements', body, headers
    if writer in ('create_requisition', 'approve_requisition'):
        body = {
            'work_id': catalog['work']['id'], 'priority': 'NORMAL',
            'notes': 'Solicitação de teste',
            'items': [{'material_id': catalog['material']['id'], 'quantity': 1}],
        }
        path = '/api/requisitions'
        if writer == 'approve_requisition':
            target = successful(admin.post(path, json=body))
            return 'POST', f"{path}/{target['id']}/action", {'action': 'APROVAR'}, headers
        return 'POST', path, body, headers
    if writer in ('create_ticket', 'comment_ticket', 'update_ticket'):
        path = '/api/tickets'
        body = {
            'title': 'Verificação de equipamento', 'description': 'Chamado de teste',
            'priority': 'NORMAL', 'work_id': catalog['work']['id'],
        }
        if writer == 'create_ticket':
            return 'POST', path, body, headers
        target = successful(admin.post(path, json=body))
        if writer == 'comment_ticket':
            return 'POST', f"{path}/{target['id']}/comments", {'body': 'Inspeção iniciada'}, headers
        return 'PATCH', f"{path}/{target['id']}", {'status': 'EM_ANDAMENTO'}, headers
    assert writer in ('open_maintenance', 'close_maintenance')
    material = catalog['create'](
        'materials', code='PAT-MAT', description='Furadeira de teste',
        category_id=catalog['category']['id'], unit='UN', minimum_stock=0,
        individualizable=True, status='ATIVO',
    )
    equipment = catalog['create'](
        'equipment', asset_tag='PAT-001', material_id=material['id'],
        location_id=catalog['origin']['id'], condition='BOA', status='DISPONIVEL',
    )
    path = '/api/maintenance'
    body = {'equipment_id': equipment['id'], 'defect': 'Cabo rompido'}
    if writer == 'close_maintenance':
        target = successful(admin.post(path, json=body))
        return 'POST', f"{path}/{target['id']}/close", {
            'resolution': 'Cabo substituído', 'condition': 'BOA',
        }, headers
    return 'POST', path, body, headers


@pytest.mark.parametrize('writer', WRITERS)
@pytest.mark.parametrize('state', REVOCATIONS)
def test_revoked_authority_cannot_write_or_replay(admin, catalog, monkeypatch, writer, state):
    method, path, body, headers = request_for(writer, admin, catalog)
    actor = successful(admin.get('/api/auth/me'))
    assert actor['role'] == 'ADMIN'
    observed = race_before_writer(monkeypatch, actor['id'], state)

    response = admin.request(method, path, json=body, headers=headers)

    assert observed['writers'] == 1, 'The request must reach a writer after initial authorization.'
    assert response.status_code == (403 if state == 'consultation_only' else 401), response.text
    assert snapshot() == observed['baseline'], 'Revoked requests must have no business or audit effects.'


@pytest.mark.parametrize('writer', ('create_user', 'edit_user'))
@pytest.mark.parametrize('state', ('session_removed', 'inactive', 'consultation_only'))
def test_revocation_during_password_hashing_cannot_manage_users(admin, catalog, monkeypatch, writer, state):
    from app import main

    method, path, body, headers = request_for(writer, admin, catalog)
    if writer == 'edit_user':
        body['password'] = 'Nova-Senha-Teste-2026'
    actor = successful(admin.get('/api/auth/me'))
    original_hash = main.hash_password
    observed = {'hashes': 0, 'baseline': None}

    def hashing_after_revocation(value):
        observed['hashes'] += 1
        revoke(actor['id'], state)
        observed['baseline'] = snapshot()
        return original_hash(value)

    monkeypatch.setattr(main, 'hash_password', hashing_after_revocation)

    response = admin.request(method, path, json=body, headers=headers)

    assert observed['hashes'] == 1
    assert response.status_code == (403 if state == 'consultation_only' else 401), response.text
    assert snapshot() == observed['baseline']


@pytest.mark.parametrize('writer', ('create_user', 'edit_user', 'approve_requisition', 'new_adjustment', 'replayed_adjustment'))
def test_demotion_to_operator_cannot_reuse_admin_privileges(admin, catalog, monkeypatch, writer):
    method, path, body, headers = request_for(writer, admin, catalog)
    actor = successful(admin.get('/api/auth/me'))
    observed = race_before_writer(monkeypatch, actor['id'], 'operator_only')

    response = admin.request(method, path, json=body, headers=headers)

    assert observed['writers'] == 1
    assert response.status_code == 403, response.text
    assert snapshot() == observed['baseline']


def test_demotion_retains_current_operator_permissions(admin, catalog, monkeypatch):
    actor = successful(admin.get('/api/auth/me'))
    observed = race_before_writer(monkeypatch, actor['id'], 'operator_only')

    response = admin.post('/api/movements', json=movement(catalog), headers={'Idempotency-Key': str(uuid.uuid4())})

    assert observed['writers'] == 1
    created = successful(response)
    assert response.status_code == 201
    with connect() as db:
        row = db.execute('SELECT * FROM movements WHERE id=?', (created['id'],)).fetchone()
        assert row['user_id'] == actor['id']
        assert row['quantity'] == 5000
        assert db.execute('SELECT quantity FROM balances WHERE material_id=? AND location_id=?', (
            catalog['material']['id'], catalog['origin']['id'],
        )).fetchone()['quantity'] == 5000
        assert db.execute("SELECT COUNT(*) AS total FROM audit WHERE entity='movements' AND record_id=?", (created['id'],)).fetchone()['total'] == 1
    current = successful(admin.get('/api/auth/me'))
    assert current['role'] == 'OPERADOR'
    assert set(current) == {'id', 'username', 'name', 'role', 'active'}


def test_session_expiring_before_writer_cannot_replay_cached_movement(admin, catalog, monkeypatch):
    method, path, body, headers = request_for('replayed_movement', admin, catalog)
    actor = successful(admin.get('/api/auth/me'))
    observed = race_before_writer(monkeypatch, actor['id'], 'session_expired')

    response = admin.request(method, path, json=body, headers=headers)

    assert observed['writers'] == 1
    assert response.status_code == 401, response.text
    assert snapshot() == observed['baseline']
