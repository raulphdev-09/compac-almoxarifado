"""Credential/origin regressions; fixtures only target disposable databases."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from app import security
from conftest import ADMIN_PASSWORD, WRITE_HEADERS


BAD_PASSWORD = 'Incorrect-Audit-Password'


def authenticate(client, username='admin', password=BAD_PASSWORD, **options):
    return client.post('/api/auth/login', json={'username': username, 'password': password}, **options)


def attempt_rows():
    with connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM auth_attempts')]


def test_failures_persist_across_clients_and_success_of_other_account(admin):
    created = admin.post('/api/users', json={
        'name': 'Reader', 'username': 'reader', 'password': ADMIN_PASSWORD, 'role': 'CONSULTA',
    })
    assert created.status_code == 201
    for _ in range(9):
        assert authenticate(admin).status_code == 401
    assert authenticate(admin, 'reader', ADMIN_PASSWORD).status_code == 200
    # Another TestClient models another process/client reading the shared DB.
    with TestClient(app, headers=WRITE_HEADERS, client=('198.51.100.3', 50000)) as other:
        assert authenticate(other, ' ADMIN ').status_code == 401
        response = authenticate(other, 'admin', ADMIN_PASSWORD)
        assert response.status_code == 429
        assert response.headers['retry-after'] == '300'
    assert len(attempt_rows()) == 10


def test_account_limit_spans_origins_and_ignores_forwarded_headers(admin):
    for index in range(10):
        with TestClient(app, headers=WRITE_HEADERS, client=(f'198.51.100.{index + 10}', 50000)) as client:
            response = authenticate(client, 'ADMIN' if index % 2 else 'admin')
            assert response.status_code == 401
    with TestClient(app, headers=WRITE_HEADERS, client=('203.0.113.2', 50000)) as client:
        assert authenticate(client).status_code == 429
    assert len({row['account_hash'] for row in attempt_rows()}) == 1


def test_origin_limit_cannot_be_evaded_by_forwarded_for(admin):
    # Unknown usernames receive the same credential response and share origin
    # protection, even if the caller varies X-Forwarded-For/X-Real-IP.
    for index in range(30):
        response = authenticate(admin, f'unknown-{index}', headers={
            'X-Forwarded-For': f'198.51.100.{index + 1}', 'X-Real-IP': f'203.0.113.{index + 1}',
        })
        assert response.status_code == 401
    assert authenticate(admin, 'another-unknown').status_code == 429
    rows = attempt_rows()
    assert len(rows) == 30
    assert len({row['origin_hash'] for row in rows}) == 1
    assert all(len(row['origin_hash']) == 64 and len(row['account_hash']) == 64 for row in rows)


def test_failure_window_expiry_purges_short_lived_identifiers(admin, monkeypatch):
    clock = [2_000_000_000]
    monkeypatch.setattr(security.time, 'time', lambda: clock[0])
    for _ in range(10):
        assert authenticate(admin).status_code == 401
    assert authenticate(admin, password=ADMIN_PASSWORD).status_code == 429
    clock[0] += 299
    assert authenticate(admin).status_code == 429
    clock[0] += 1
    assert authenticate(admin, password=ADMIN_PASSWORD).status_code == 200
    assert attempt_rows() == []


def test_concurrent_credential_failures_obey_atomic_limit(admin):
    barrier = Barrier(12)

    def fail_login(index):
        with TestClient(app, headers=WRITE_HEADERS, client=(f'198.51.100.{index + 100}', 50000)) as client:
            barrier.wait(timeout=10)
            return authenticate(client).status_code

    with ThreadPoolExecutor(max_workers=12) as executor:
        statuses = list(executor.map(fail_login, range(12)))
    assert statuses.count(401) == 10
    assert statuses.count(429) == 2
    assert len(attempt_rows()) == 10


def test_failure_audit_commits_without_credentials_and_limits_block_events(admin):
    for _ in range(10):
        assert authenticate(admin).status_code == 401
    for _ in range(3):
        assert authenticate(admin).status_code == 429
    with connect() as db:
        events = [dict(row) for row in db.execute(
            "SELECT * FROM audit WHERE entity='authentication' ORDER BY id"
        )]
    assert sum(row['action'] == 'LOGIN_FALHOU' for row in events) == 10
    assert sum(row['action'] == 'CREDENCIAL_BLOQUEADA' for row in events) == 1
    for event in events:
        assert event['user_id'] is None
        assert event['record_id'] is None
        details = json.loads(event['details'])
        assert set(details) == {'account_hash', 'origin_hash'}
        assert all(len(value) == 64 for value in details.values())
        assert BAD_PASSWORD not in event['details']
        assert 'admin' not in event['details']


@pytest.mark.parametrize('headers, expected', [
    ({'Origin': 'http://testserver'}, 201),
    ({'Referer': 'http://testserver/page?view=materials'}, 201),
    ({'Sec-Fetch-Site': 'same-origin'}, 201),
    ({}, 201),  # Explicit header-only CLI/TestClient contract.
    ({'Origin': 'https://evil.invalid'}, 403),
    ({'Origin': 'null'}, 403),
    ({'Origin': 'http://testserver.attacker.invalid'}, 403),
    ({'Referer': 'https://evil.invalid/page'}, 403),
    ({'Referer': 'not-a-url'}, 403),
    ({'Sec-Fetch-Site': 'cross-site'}, 403),
    ({'Sec-Fetch-Site': 'same-site'}, 403),
    ({'Sec-Fetch-Site': 'none'}, 403),
    ({'Origin': 'http://testserver', 'Sec-Fetch-Site': 'cross-site'}, 403),
    ({'X-Compac-Client': ''}, 403),
])
def test_origin_referer_and_fetch_metadata_policy(admin, headers, expected):
    response = admin.post('/api/catalog/categories', json={'name': 'Origin policy audit'}, headers=headers)
    assert response.status_code == expected
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('configured', ['not-a-url', 'https://trusted.invalid/path', 'https://user@trusted.invalid'])
def test_invalid_public_url_configuration_fails_closed(admin, monkeypatch, configured):
    monkeypatch.setenv('COMPAC_PUBLIC_URL', configured)
    response = admin.post('/api/catalog/categories', json={'name': 'Must be refused'})
    assert response.status_code == 403
    assert configured not in response.text


def test_own_password_requires_current_password_and_revokes_every_session(admin):
    with TestClient(app, headers=WRITE_HEADERS) as other:
        assert authenticate(other, password=ADMIN_PASSWORD).status_code == 200
        wrong = admin.post('/api/auth/password', json={
            'current_password': BAD_PASSWORD, 'new_password': 'Replacement-Password-2026',
        })
        assert wrong.status_code == 403
        assert admin.get('/api/auth/me').status_code == 200
        response = admin.post('/api/auth/password', json={
            'current_password': ADMIN_PASSWORD, 'new_password': 'Replacement-Password-2026',
        })
        assert response.status_code == 200
        assert response.json() == {'ok': True, 'reauthenticate': True}
        assert 'max-age=0' in response.headers['set-cookie'].lower()
        assert admin.get('/api/auth/me').status_code == 401
        assert other.get('/api/auth/me').status_code == 401
        assert authenticate(other, password=ADMIN_PASSWORD).status_code == 401
        assert authenticate(other, password='Replacement-Password-2026').status_code == 200
    with connect() as db:
        row = db.execute("SELECT details FROM audit WHERE action='TROCAR_SENHA'").fetchone()
        assert json.loads(row['details']) == {}


def test_consulta_can_change_only_own_password(admin):
    created = admin.post('/api/users', json={
        'name': 'Read only', 'username': 'readonly', 'password': ADMIN_PASSWORD, 'role': 'CONSULTA',
    })
    assert created.status_code == 201
    with TestClient(app, headers=WRITE_HEADERS) as reader:
        assert authenticate(reader, 'readonly', ADMIN_PASSWORD).status_code == 200
        assert reader.patch('/api/users/1', json={'password': 'Another-Password-2026'}).status_code == 403
        assert reader.post('/api/auth/password', json={
            'current_password': ADMIN_PASSWORD, 'new_password': 'Own-Password-2026',
        }).status_code == 200
    assert authenticate(admin, password=ADMIN_PASSWORD).status_code == 200


def test_wrong_current_password_uses_same_persistent_credential_limits(admin):
    for _ in range(10):
        assert admin.post('/api/auth/password', json={
            'current_password': BAD_PASSWORD, 'new_password': 'Replacement-Password-2026',
        }).status_code == 403
    assert admin.post('/api/auth/password', json={
        'current_password': ADMIN_PASSWORD, 'new_password': 'Replacement-Password-2026',
    }).status_code == 429
    assert len(attempt_rows()) == 10


def test_password_change_requires_authenticated_session(client):
    response = client.post('/api/auth/password', json={
        'current_password': ADMIN_PASSWORD, 'new_password': 'Replacement-Password-2026',
    })
    assert response.status_code == 401


def test_password_change_audit_failure_rolls_back_hash_and_revocation(admin, monkeypatch):
    from app import main

    original_audit = main.audit

    def fail_password_audit(db, user_id, action, *args, **kwargs):
        if action == 'TROCAR_SENHA':
            raise RuntimeError('Simulated password audit failure')
        return original_audit(db, user_id, action, *args, **kwargs)

    monkeypatch.setattr(main, 'audit', fail_password_audit)
    with pytest.raises(RuntimeError, match='Simulated password audit failure'):
        admin.post('/api/auth/password', json={
            'current_password': ADMIN_PASSWORD, 'new_password': 'Replacement-Password-2026',
        })
    monkeypatch.setattr(main, 'audit', original_audit)
    assert admin.get('/api/auth/me').status_code == 200
    assert authenticate(admin, password=ADMIN_PASSWORD).status_code == 200
    assert authenticate(admin, password='Replacement-Password-2026').status_code == 401


@pytest.mark.parametrize('body', [
    {'current_password': ADMIN_PASSWORD, 'new_password': 'short'},
    {'current_password': ADMIN_PASSWORD, 'new_password': ADMIN_PASSWORD},
    {'current_password': ADMIN_PASSWORD},
    {'current_password': ADMIN_PASSWORD, 'new_password': 'Replacement-Password-2026', 'user_id': 2},
])
def test_password_change_rejects_invalid_contract_without_revoking_session(admin, body):
    assert admin.post('/api/auth/password', json=body).status_code == 422
    assert admin.get('/api/auth/me').status_code == 200
