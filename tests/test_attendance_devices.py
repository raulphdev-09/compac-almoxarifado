import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest

from app.attendance import service
from app.attendance.device import COOKIE
from app.db import connect, Database
from conftest import ADMIN_PASSWORD


P = '/api/v1/attendance'


def success(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def device(admin, catalog, monkeypatch, client_factory):
    monkeypatch.setenv('COMPAC_ENV', 'test')
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'demo')
    secure_admin = client_factory(base_url='https://testserver')
    secure_admin.cookies.update(admin.cookies)
    admin = secure_admin
    terminal = success(admin.post(P + '/terminals', json={'name': 'Tablet fictício', 'work_id': catalog['work']['id']}), 201)
    code = success(admin.post(P + f"/terminals/{terminal['id']}/activation"), 201)['activation_code']
    def secure_factory(**options):
        return client_factory(**{'base_url': 'https://testserver', **options})
    client = secure_factory()
    success(client.post(P + '/terminal/activate', json={'activation_code': code}), 201)
    return {'admin': admin, 'catalog': catalog, 'terminal': terminal, 'client': client, 'code': code, 'factory': secure_factory}


def authorize(device, registration=None):
    return device['client'].post(P + '/terminal/test-authorizations', json={
        'registration': registration or device['catalog']['employee']['registration'], 'acknowledgement': 'TESTE_SUPERVISIONADO'})


def mark(device, token, key=None, kind='ENTRADA', **extra):
    return device['client'].post(P + '/terminal/mark', json={'authorization': token, 'mark_type': kind, **extra}, headers={'Idempotency-Key': key or str(uuid.uuid4())})


def rows():
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM attendance_records ORDER BY id')]


@pytest.mark.parametrize('kind', ['ENTRADA', 'INICIO_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA'])
def test_device_records_minimal_reply_using_bound_work(device, kind):
    token = success(authorize(device), 201)['authorization']
    reply = success(mark(device, token, kind=kind), 201)
    assert set(reply) == {'record_uid', 'mark_type', 'marked_at', 'verification_result', 'experimental'}
    assert reply['experimental'] is True and reply['verification_result'] == 'SIMULADO'
    assert rows()[0]['work_id'] == device['catalog']['work']['id']
    assert rows()[0]['terminal_id'] == device['terminal']['id']
    assert rows()[0]['is_test'] == 1


def test_credential_is_private_scoped_cookie_and_secrets_are_hashed(device):
    raw = device['client'].cookies.get(COOKIE)
    assert raw
    with connect() as db:
        stored = json.dumps([dict(r) for r in db.execute('SELECT * FROM attendance_device_sessions')])
        codes = json.dumps([dict(r) for r in db.execute('SELECT * FROM attendance_activation_codes')])
        audit = json.dumps([dict(r) for r in db.execute('SELECT details FROM audit')])
    assert raw not in stored + audit and device['code'] not in codes + audit
    assert device['client'].get('/api/users').status_code == 401
    for path in ('/records', '/terminals', '/employee/1', '/worksite/1'):
        assert device['client'].get(P + path).status_code == 401
    info = success(device['client'].get(P + '/terminal/status'))
    assert 'employee_id' not in info and 'employees' not in info


def test_activation_consumes_code_once(device):
    other = device['factory']()
    assert other.post(P + '/terminal/activate', json={'activation_code': device['code']}).status_code == 401


def test_expired_activation_is_not_consumed(device):
    code = success(device['admin'].post(P + f"/terminals/{device['terminal']['id']}/activation"), 201)['activation_code']
    with connect(write=True) as db:
        db.execute("UPDATE attendance_activation_codes SET expires_at='2000-01-01T00:00:00+00:00' WHERE used_at IS NULL")
    other = device['factory']()
    assert other.post(P + '/terminal/activate', json={'activation_code': code}).status_code == 401
    assert not other.cookies.get(COOKIE)


def test_activation_audit_failure_preserves_admin_and_unused_code(device):
    code = success(device['admin'].post(P + f"/terminals/{device['terminal']['id']}/activation"), 201)['activation_code']
    from fastapi.testclient import TestClient
    with TestClient(device['admin'].app, base_url='https://testserver', headers={'X-Compac-Client': 'web'}, raise_server_exceptions=False) as client:
        client.cookies.update(device['admin'].cookies)
        with patch.object(service, 'emit_audit', side_effect=RuntimeError('Injected activation audit failure')):
            assert client.post(P + '/terminal/activate', json={'activation_code': code}).status_code == 500
        assert client.get('/api/auth/me').status_code == 200
        success(client.post(P + '/terminal/activate', json={'activation_code': code}), 201)


def test_handoff_revokes_administrator_session(device):
    admin = device['admin']
    key = device['terminal']['id']
    code = success(admin.post(P + f'/terminals/{key}/activation'), 201)['activation_code']
    response = admin.post(P + '/terminal/activate', json={'activation_code': code})
    success(response, 201)
    cookie = next(x for x in response.headers.get_list('set-cookie') if x.startswith(COOKIE + '='))
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/api/v1/attendance/terminal' in cookie
    assert 'Max-Age=43200' in cookie
    assert admin.get('/api/auth/me').status_code == 401
    assert admin.get('/api/users').status_code == 401
    assert admin.get(P + '/terminal/status').status_code == 200


def test_https_activation_uses_secure_cookie(device):
    code = success(device['admin'].post(P + f"/terminals/{device['terminal']['id']}/activation"), 201)['activation_code']
    client = device['factory'](base_url='https://testserver')
    response = client.post(P + '/terminal/activate', json={'activation_code': code})
    success(response, 201)
    cookie = next(x for x in response.headers.get_list('set-cookie') if x.startswith(COOKIE + '='))
    assert '; Secure' in cookie


def test_rotation_and_revocation_deny_old_device_and_old_replays(device):
    token = success(authorize(device), 201)['authorization']
    key = str(uuid.uuid4())
    success(mark(device, token, key), 201)
    success(device['admin'].post(P + f"/terminals/{device['terminal']['id']}/activation"), 201)
    assert mark(device, token, key).status_code == 401
    assert len(rows()) == 1


def test_terminal_revocation_blocks_unexpired_device(device):
    token = success(authorize(device), 201)['authorization']
    success(device['admin'].post(P + f"/terminals/{device['terminal']['id']}/revoke"))
    assert device['client'].get(P + '/terminal/status').status_code == 403
    assert mark(device, token).status_code == 403
    assert rows() == []


def test_expired_device_and_inactive_issuer_are_denied(device):
    with connect(write=True) as db:
        db.execute("UPDATE attendance_device_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    assert device['client'].get(P + '/terminal/status').status_code == 401


def test_inactive_issuer_revokes_terminal_privileges(device):
    with connect(write=True) as db:
        db.execute('UPDATE users SET active=0 WHERE id=?', (1,))
    assert device['client'].get(P + '/terminal/status').status_code == 403


def test_invalid_inactive_and_wrong_work_matriculas_have_same_reply(device):
    replies = [authorize(device, 'DOES-NOT-EXIST')]
    employee = device['catalog']['employee']
    data = {k: employee[k] for k in ('registration', 'name', 'job_title', 'work_id', 'status')}
    success(device['admin'].put('/api/catalog/employees/' + str(employee['id']), json={**data, 'status': 'INATIVO'}))
    replies.append(authorize(device))
    success(device['admin'].put('/api/catalog/employees/' + str(employee['id']), json={**data, 'work_id': device['catalog']['other_work']['id']}))
    replies.append(authorize(device))
    assert all(r.status_code == 403 for r in replies)
    assert len({r.text for r in replies}) == 1
    assert employee['name'] not in replies[0].text


def test_body_cannot_supply_verified_identity_work_or_clock(device):
    token = success(authorize(device), 201)['authorization']
    for extra in ({'work_id': 2}, {'terminal_id': 2}, {'face_verified': True}, {'marked_at': '2000-01-01'}, {'image': 'data:image/png;base64,AAAA'}):
        assert mark(device, token, **extra).status_code == 422
    assert rows() == []
    success(mark(device, token), 201)


def test_device_cannot_use_admin_authorization_or_another_device_token(device):
    issued = success(device['admin'].post(P + '/test-authorizations', json={'registration': device['catalog']['employee']['registration'], 'terminal_id': device['terminal']['id'], 'acknowledgement': 'TESTE_SUPERVISIONADO'}), 201)
    assert mark(device, issued['authorization']).status_code == 403
    terminal = success(device['admin'].post(P + '/terminals', json={'name': 'Outro tablet', 'work_id': device['catalog']['work']['id']}), 201)
    code = success(device['admin'].post(P + f"/terminals/{terminal['id']}/activation"), 201)['activation_code']
    other = device['factory']()
    success(other.post(P + '/terminal/activate', json={'activation_code': code}), 201)
    token = success(authorize(device), 201)['authorization']
    different = dict(device, client=other)
    assert mark(different, token).status_code == 403
    success(mark(device, token), 201)


def test_replay_is_same_result_even_after_verification_expiry(device):
    token = success(authorize(device), 201)['authorization']
    key = str(uuid.uuid4())
    first = success(mark(device, token, key), 201)
    with connect(write=True) as db:
        db.execute("UPDATE attendance_authorizations SET expires_at='2000-01-01T00:00:00+00:00'")
    assert success(mark(device, token, key), 201) == first
    assert mark(device, token, key, kind='SAIDA').status_code == 409
    assert len(rows()) == 1


def test_concurrent_replay_and_different_legitimate_marks(device):
    token = success(authorize(device), 201)['authorization']
    key, barrier = str(uuid.uuid4()), Barrier(2)
    def call(_):
        client = device['factory']()
        client.cookies.update(device['client'].cookies)
        barrier.wait(timeout=10)
        return mark(dict(device, client=client), token, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(call, (1, 2)))
    assert all(r.status_code == 201 for r in responses)
    assert responses[0].json() == responses[1].json()
    success(mark(device, success(authorize(device), 201)['authorization']), 201)
    assert len(rows()) == 2


def test_audit_failure_rolls_back_mark_and_can_retry(device):
    token = success(authorize(device), 201)['authorization']
    key = str(uuid.uuid4())
    from fastapi.testclient import TestClient
    with TestClient(device['client'].app, base_url='https://testserver', headers={'X-Compac-Client': 'web'}, raise_server_exceptions=False) as client:
        client.cookies.update(device['client'].cookies)
        with patch.object(service, 'emit_audit', side_effect=RuntimeError('Injected device test failure')):
            assert mark(dict(device, client=client), token, key).status_code == 500
    assert rows() == []
    success(mark(device, token, key), 201)


def test_activation_rate_and_logout(device):
    client = device['factory']()
    # The fixture's successful activation is itself one counted attempt.
    for _ in range(29):
        assert client.post(P + '/terminal/activate', json={'activation_code': 'x' * 43}).status_code == 401
    assert client.post(P + '/terminal/activate', json={'activation_code': 'x' * 43}).status_code == 429
    success(device['client'].post(P + '/terminal/logout'))
    assert device['client'].get(P + '/terminal/status').status_code == 401


def test_production_mode_denies_device_calls(device, monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    assert device['client'].get(P + '/terminal/status').status_code == 404
    assert authorize(device).status_code == 404


def test_nonlocal_cleartext_transport_is_rejected_without_consuming_code(device):
    from fastapi.testclient import TestClient
    code = success(device['admin'].post(P + f"/terminals/{device['terminal']['id']}/activation"), 201)['activation_code']
    with TestClient(device['admin'].app, base_url='http://external.invalid', headers={'X-Compac-Client': 'web'}) as client:
        assert client.post(P + '/terminal/activate', json={'activation_code': code}).status_code == 426
    other = device['factory']()
    success(other.post(P + '/terminal/activate', json={'activation_code': code}), 201)
