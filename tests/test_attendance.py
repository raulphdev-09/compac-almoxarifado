"""Experimental attendance API checks using fictitious workers and temporary DBs.

No photograph, camera, biometric vector, terminal secret or production database
is used. Every accepted mark must explicitly remain a supervised test record.
"""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.db import Database, connect
from app.attendance import service
from conftest import ADMIN_PASSWORD, WRITE_HEADERS


BASE = '/api/v1/attendance'
MARK_TYPES = ('ENTRADA', 'INICIO_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA')


def test_demo_rejects_remote_database_without_connecting(monkeypatch):
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'demo')
    monkeypatch.setenv('COMPAC_ENV', 'test')
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example:example@remote.invalid/test')
    with pytest.raises(HTTPException) as error:
        service.demo_only()
    assert error.value.status_code == 404


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def attendance(admin, catalog, monkeypatch):
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'demo')
    monkeypatch.setenv('COMPAC_ENV', 'test')
    terminal = ok(admin.post(BASE + '/terminals', json={
        'name': 'Terminal fictício', 'work_id': catalog['work']['id'],
    }), 201)
    return {'client': admin, 'catalog': catalog, 'terminal': terminal}


def authorize(attendance, **overrides):
    body = {
        'registration': attendance['catalog']['employee']['registration'],
        'terminal_id': attendance['terminal']['id'],
        'acknowledgement': 'TESTE_SUPERVISIONADO',
    }
    return attendance['client'].post(BASE + '/test-authorizations', json={**body, **overrides})


def mark(attendance, authorization, kind='ENTRADA', *, key=None, client=None, **extra):
    return (client or attendance['client']).post(
        BASE + '/mark',
        json={'authorization': authorization, 'mark_type': kind, **extra},
        headers={'Idempotency-Key': key or str(uuid.uuid4())},
    )


def records(attendance, **params):
    return ok(attendance['client'].get(BASE + '/records', params=params))


def state():
    with connect() as db:
        return {
            table: [dict(row) for row in db.execute(f'SELECT * FROM {table}')]
            for table in ('attendance_records', 'attendance_authorizations', 'audit', 'idempotency_requests')
        }


@pytest.mark.parametrize('kind', MARK_TYPES)
def test_supervised_mark_uses_existing_employee_work_and_server_time(attendance, kind):
    issued = ok(authorize(attendance), 201)
    before = datetime.now(timezone.utc)
    result = ok(mark(attendance, issued['authorization'], kind), 201)
    after = datetime.now(timezone.utc)
    page = records(attendance)
    assert page['total'] == 1
    row = page['items'][0]
    assert row['id'] == result['id']
    assert row['employee_id'] == attendance['catalog']['employee']['id']
    assert row['work_id'] == attendance['catalog']['work']['id']
    assert row['terminal_id'] == attendance['terminal']['id']
    assert row['mark_type'] == kind
    assert row['verification_method'] == 'DEMO_SUPERVISIONADO'
    assert row['verification_result'] == 'SIMULADO'
    assert row['is_test'] in (True, 1)
    assert before <= datetime.fromisoformat(row['marked_at']) <= after


@pytest.mark.parametrize('environment', [
    {'COMPAC_ATTENDANCE_MODE': None, 'COMPAC_ENV': 'test'},
    {'COMPAC_ATTENDANCE_MODE': 'disabled', 'COMPAC_ENV': 'test'},
    {'COMPAC_ATTENDANCE_MODE': 'demo', 'COMPAC_ENV': None},
    {'COMPAC_ATTENDANCE_MODE': 'demo', 'COMPAC_ENV': 'production'},
    {'COMPAC_ATTENDANCE_MODE': 'demo', 'COMPAC_ENV': 'test', 'RENDER': 'true'},
])
def test_demo_is_disabled_by_default_and_in_production(attendance, monkeypatch, environment):
    before = state()
    for name, value in environment.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert authorize(attendance).status_code == 404
    assert attendance['client'].get(BASE + '/records').status_code == 404
    assert state() == before


def test_test_authorization_requires_explicit_supervision(attendance):
    assert authorize(attendance, acknowledgement='').status_code == 422
    assert authorize(attendance, acknowledgement='face_verified=true').status_code == 422
    assert authorize(attendance, face_verified=True).status_code == 422
    assert state()['attendance_authorizations'] == []


def test_nonexistent_and_inactive_employees_are_not_authorized(attendance):
    assert authorize(attendance, registration='NOT-EXISTING').status_code in (404, 422)
    employee = attendance['catalog']['employee']
    body = {key: employee[key] for key in ('registration', 'name', 'job_title', 'work_id', 'status')}
    ok(attendance['client'].put('/api/catalog/employees/' + str(employee['id']), json={**body, 'status': 'INATIVO'}))
    assert authorize(attendance).status_code in (409, 422)
    assert records(attendance)['total'] == 0


def test_terminal_work_controls_employee_association(attendance):
    other = ok(attendance['client'].post(BASE + '/terminals', json={
        'name': 'Terminal de outra obra', 'work_id': attendance['catalog']['other_work']['id'],
    }), 201)
    assert authorize(attendance, terminal_id=other['id']).status_code == 403
    assert records(attendance)['total'] == 0


def test_authorization_and_mark_never_accept_client_verified_or_time(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    for extra in ({'face_verified': True}, {'recorded_at': '2000-01-01T00:00:00Z'},
                  {'work_id': attendance['catalog']['other_work']['id']}, {'image': 'fake-image'}):
        assert mark(attendance, token, **extra).status_code == 422
    assert records(attendance)['total'] == 0
    ok(mark(attendance, token), 201)


def test_authorization_is_hashed_and_single_use(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    assert token not in json.dumps(state(), ensure_ascii=False)
    assert mark(attendance, 'invalid-authorization').status_code in (401, 403, 409, 422)
    ok(mark(attendance, token), 201)
    assert mark(attendance, token).status_code == 409
    assert records(attendance)['total'] == 1
    assert token not in json.dumps(state(), ensure_ascii=False)


def test_expired_authorization_does_not_mark(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    with connect(write=True) as db:
        db.execute('UPDATE attendance_authorizations SET expires_at=?', ('2000-01-01T00:00:00+00:00',))
    assert mark(attendance, token).status_code in (401, 403, 409)
    assert records(attendance)['total'] == 0


def test_terminal_revocation_invalidates_pending_authorizations(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    ok(attendance['client'].post(BASE + '/terminals/' + str(attendance['terminal']['id']) + '/revoke'))
    assert authorize(attendance).status_code in (403, 409, 422)
    assert mark(attendance, token).status_code in (403, 409, 422)
    assert records(attendance)['total'] == 0


def test_employee_deactivation_after_authorization_is_rechecked(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    employee = attendance['catalog']['employee']
    body = {key: employee[key] for key in ('registration', 'name', 'job_title', 'work_id', 'status')}
    ok(attendance['client'].put('/api/catalog/employees/' + str(employee['id']), json={**body, 'status': 'INATIVO'}))
    assert mark(attendance, token).status_code in (403, 409, 422)
    assert records(attendance)['total'] == 0


def test_employee_work_change_after_authorization_is_rechecked(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    employee = attendance['catalog']['employee']
    body = {key: employee[key] for key in ('registration', 'name', 'job_title', 'work_id', 'status')}
    ok(attendance['client'].put('/api/catalog/employees/' + str(employee['id']), json={
        **body, 'work_id': attendance['catalog']['other_work']['id'],
    }))
    assert mark(attendance, token).status_code == 403
    assert records(attendance)['total'] == 0


def test_authorization_cannot_be_used_by_another_administrator(attendance, client_factory):
    token = ok(authorize(attendance), 201)['authorization']
    ok(attendance['client'].post('/api/users', json={
        'name': 'Outro administrador fictício', 'username': 'other-admin-attendance',
        'password': ADMIN_PASSWORD, 'role': 'ADMIN',
    }), 201)
    session = client_factory()
    ok(session.post('/api/auth/login', json={'username': 'other-admin-attendance', 'password': ADMIN_PASSWORD}))
    assert mark(attendance, token, client=session).status_code == 403
    assert records(attendance)['total'] == 0


def test_terminals_reference_existing_works_without_creating_duplicates(attendance):
    client = attendance['client']
    before = ok(client.get('/api/catalog/works'))
    ok(client.post(BASE + '/terminals', json={
        'name': 'Segundo dispositivo fictício', 'work_id': attendance['catalog']['work']['id'],
    }), 201)
    assert ok(client.get('/api/catalog/works')) == before
    assert client.post(BASE + '/terminals', json={'name': 'Inválido', 'work_id': 999999}).status_code == 404


def test_repeated_request_returns_original_without_duplicate(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    key = str(uuid.uuid4())
    first = ok(mark(attendance, token, key=key), 201)
    committed = state()
    assert ok(mark(attendance, token, key=key), 201) == first
    assert state() == committed
    assert mark(attendance, token, 'SAIDA', key=key).status_code == 409
    assert state() == committed


def test_mark_requires_idempotency_key(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    assert attendance['client'].post(BASE + '/mark', json={
        'authorization': token, 'mark_type': 'ENTRADA',
    }).status_code == 422
    assert records(attendance)['total'] == 0


def test_simultaneous_retries_produce_one_mark(attendance, client_factory):
    token = ok(authorize(attendance), 201)['authorization']
    key, barrier = str(uuid.uuid4()), Barrier(2)
    sessions = [client_factory(), client_factory()]
    for session in sessions:
        ok(session.post('/api/auth/login', json={'username': 'admin', 'password': ADMIN_PASSWORD}))

    def submit(session):
        barrier.wait(timeout=10)
        return mark(attendance, token, key=key, client=session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, sessions))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert records(attendance)['total'] == 1


def test_close_legitimate_marks_are_preserved(attendance):
    first = ok(mark(attendance, ok(authorize(attendance), 201)['authorization']), 201)
    second = ok(mark(attendance, ok(authorize(attendance), 201)['authorization']), 201)
    assert first['id'] != second['id']
    assert records(attendance)['total'] == 2


def test_marks_persist_after_restart_and_have_no_edit_or_delete_route(attendance, client_factory):
    result = ok(mark(attendance, ok(authorize(attendance), 201)['authorization']), 201)
    restarted = client_factory()
    restarted.cookies.update(attendance['client'].cookies)
    page = ok(restarted.get(BASE + '/records'))
    assert page['items'][0]['record_uid'] == result['record_uid']
    before = state()
    for method in ('patch', 'delete'):
        response = getattr(restarted, method)(BASE + '/records/' + str(result['id']))
        assert response.status_code in (404, 405)
    assert state() == before


def test_audit_failure_rolls_back_mark_and_token_use(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    key = str(uuid.uuid4())
    before, original = state(), Database.execute

    def fail_audit(db, sql, params=()):
        if sql.lstrip().upper().startswith('INSERT INTO AUDIT'):
            raise RuntimeError('discardable attendance audit failure')
        return original(db, sql, params)

    with TestClient(attendance['client'].app, headers=WRITE_HEADERS, raise_server_exceptions=False) as session:
        session.cookies.update(attendance['client'].cookies)
        with patch.object(Database, 'execute', fail_audit):
            assert mark(attendance, token, key=key, client=session).status_code == 500
    assert state() == before
    ok(mark(attendance, token, key=key), 201)


def test_http_error_after_insert_does_not_commit_partial_mark(attendance):
    token = ok(authorize(attendance), 201)['authorization']
    before = state()
    key = str(uuid.uuid4())
    with patch.object(service, 'emit_audit', side_effect=HTTPException(409, 'Injected test rejection')):
        assert mark(attendance, token, key=key).status_code == 409
    assert state() == before
    ok(mark(attendance, token, key=key), 201)


def test_http_error_after_authorization_insert_rolls_back_token(attendance):
    before = state()
    with patch.object(service, 'emit_audit', side_effect=HTTPException(409, 'Injected test rejection')):
        assert authorize(attendance).status_code == 409
    assert state() == before


def test_test_attempt_limit_persists_without_creating_authorizations(attendance):
    for _ in range(30):
        assert authorize(attendance, registration='NOT-EXISTING').status_code == 404
    response = authorize(attendance)
    assert response.status_code == 429
    assert response.headers['retry-after'] == '300'
    assert state()['attendance_authorizations'] == []


@pytest.mark.parametrize('role', ['OPERADOR', 'CONSULTA'])
def test_phase_one_is_administrator_only(attendance, client_factory, role):
    ok(attendance['client'].post('/api/users', json={
        'name': 'Conta fictícia ' + role, 'username': role.lower(),
        'password': ADMIN_PASSWORD, 'role': role,
    }), 201)
    session = client_factory()
    ok(session.post('/api/auth/login', json={'username': role.lower(), 'password': ADMIN_PASSWORD}))
    assert session.get(BASE + '/records').status_code == 403
    assert session.get(BASE + '/terminals').status_code == 403
    assert session.post(BASE + '/test-authorizations', json={}).status_code == 403
    assert session.post(BASE + '/mark', json={}, headers={'Idempotency-Key': 'forbidden'}).status_code == 403


def test_anonymous_terminal_cannot_read_workers_or_mark(attendance, client_factory):
    session = client_factory()
    assert session.get(BASE + '/records').status_code == 401
    assert session.get(BASE + '/terminals').status_code == 401
    assert session.post(BASE + '/test-authorizations', json={}).status_code == 401
    assert session.post(BASE + '/mark', json={}).status_code == 401


def test_records_are_filterable_and_bounded(attendance):
    for kind in MARK_TYPES:
        ok(mark(attendance, ok(authorize(attendance), 201)['authorization'], kind), 201)
    page = records(attendance, limit=2, offset=1)
    assert page['total'] == 4 and len(page['items']) == 2
    assert len(records(attendance, mark_type='SAIDA')['items']) == 1
    assert records(attendance, work_id=attendance['catalog']['other_work']['id'])['total'] == 0
    assert records(attendance, employee_id=attendance['catalog']['employee']['id'])['total'] == 4
    assert attendance['client'].get(BASE + '/records', params={'limit': 101}).status_code == 422
    assert attendance['client'].get(BASE + '/records', params={'offset': -1}).status_code == 422
    assert attendance['client'].get(BASE + '/records', params={'date_from': 'not-a-date'}).status_code == 422
