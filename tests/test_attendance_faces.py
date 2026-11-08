"""Facial API contracts with a deterministic test-only adapter; no real photos.

These tests exercise authorization, encryption and transactions. The fake engine
does not measure biometric accuracy and is never installed in application code.
"""
import base64
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

pytest.importorskip('cryptography', reason='APIs faciais exigem as dependências opcionais de requirements-face.txt')

from app.attendance import service
from app.db import connect
from conftest import ADMIN_PASSWORD


P = '/api/v1/attendance'
IMAGE = base64.b64encode(b'SYNTHETIC_TEST_ADAPTER_INPUT_NOT_A_PHOTOGRAPH').decode()
PREPARED = b'SANITIZED_SYNTHETIC_REFERENCE_BYTES_NOT_A_PHOTOGRAPH'
REFERENCE_ACK = 'AUTORIZACAO_ORGANIZACIONAL_E_BASE_LEGAL_CONFIRMADAS'
VERIFY_ACK = 'VERIFICACAO_FACIAL_SUPERVISIONADA'


def success(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


class TestOnlyEngine:
    """Only injected by fixtures. No production automatic acceptance mode."""
    __test__ = False

    def __init__(self):
        self.threshold = 0.5
        self.matches = True
        self.error = None
        self.before_compare = None
        self.compare_calls = 0

    def prepare_reference(self, encoded):
        if self.error:
            raise self.error
        assert encoded == IMAGE
        return PREPARED

    def compare(self, reference, encoded):
        self.compare_calls += 1
        assert reference == PREPARED
        assert encoded == IMAGE
        if self.before_compare:
            self.before_compare()
        if self.error:
            raise self.error
        return self.matches


def reference_body(face, **extra):
    return {
        'registration': face['catalog']['employee']['registration'],
        'image_base64': IMAGE,
        'authorization_basis': 'Protocolo organizacional de teste fictício 2026-001',
        'retention_days': 7,
        'acknowledgement': REFERENCE_ACK,
        **extra,
    }


def upload(face, **extra):
    return face['admin'].post(P + '/face-reference', json=reference_body(face, **extra))


def verify(face, **extra):
    return face['client'].post(P + '/terminal/verify-face', json={
        'registration': face['catalog']['employee']['registration'],
        'image_base64': IMAGE,
        'acknowledgement': VERIFY_ACK,
        **extra,
    })


def mark(face, token, key=None, kind='ENTRADA', **extra):
    return face['client'].post(P + '/terminal/mark', json={
        'authorization': token, 'mark_type': kind, **extra,
    }, headers={'Idempotency-Key': key or str(uuid.uuid4())})


def rows(table):
    with connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM ' + table)]


@pytest.fixture
def face(admin, catalog, monkeypatch, client_factory):
    from app.attendance import face_engine

    monkeypatch.setenv('COMPAC_ENV', 'test')
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'facial')
    monkeypatch.setenv('COMPAC_FACE_SUPERVISED', '1')
    monkeypatch.setenv('COMPAC_FACE_KEY', base64.urlsafe_b64encode(bytes(range(32))).decode())
    engine = TestOnlyEngine()
    monkeypatch.setattr(face_engine, 'get_engine', lambda: engine)
    secure_admin = client_factory(base_url='https://testserver')
    secure_admin.cookies.update(admin.cookies)

    def factory(**options):
        return client_factory(**{'base_url': 'https://testserver', **options})

    data = {'admin': secure_admin, 'catalog': catalog, 'engine': engine, 'factory': factory}
    success(upload(data), 201)
    terminal = success(secure_admin.post(P + '/terminals', json={
        'name': 'Terminal facial fictício', 'work_id': catalog['work']['id'],
    }), 201)
    code = success(secure_admin.post(P + f"/terminals/{terminal['id']}/activation"), 201)['activation_code']
    client = factory()
    success(client.post(P + '/terminal/activate', json={'activation_code': code}), 201)
    return {**data, 'client': client, 'terminal': terminal}


@pytest.mark.parametrize('kind', ['ENTRADA', 'INICIO_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA'])
def test_confirmed_comparison_uses_server_clock_and_preserves_true_method(face, kind):
    before = datetime.now(timezone.utc)
    authorization = success(verify(face), 201)
    assert authorization['expires_in'] == 60
    reply = success(mark(face, authorization['authorization'], kind=kind), 201)
    after = datetime.now(timezone.utc)
    assert reply['verification_result'] == 'CORRESPONDENCIA_CONFIRMADA'
    assert reply['experimental'] is True
    assert not {'employee_id', 'name', 'image_base64', 'reference_version', 'authorization'} & set(reply)
    stored = rows('attendance_facial_records')
    assert len(stored) == 1
    row = stored[0]
    assert row['verification_method'] == 'FACIAL_EXPERIMENTAL'
    assert row['verification_result'] == 'CORRESPONDENCIA_CONFIRMADA'
    assert row['is_test'] == 1
    assert row['work_id'] == face['catalog']['work']['id']
    assert row['terminal_id'] == face['terminal']['id']
    assert row['mark_type'] == kind
    assert before <= datetime.fromisoformat(row['marked_at']) <= after
    assert rows('attendance_records') == []


def test_reference_ciphertext_and_audit_never_include_image_or_secret(face):
    reference = rows('attendance_face_references')[0]
    token = success(verify(face), 201)['authorization']
    serialized = json.dumps(rows('attendance_face_references') + rows('attendance_face_grants') + rows('audit'))
    assert IMAGE not in serialized and PREPARED.decode() not in serialized and token not in serialized
    assert reference['encrypted_image'] != PREPARED.decode()
    assert reference['authorized_by'] == 1
    assert len(reference['version_uid']) >= 16
    assert reference['authorization_basis'] == reference_body(face)['authorization_basis']
    grant = rows('attendance_face_grants')[0]
    assert grant['token_hash'] == hashlib.sha256(token.encode()).hexdigest()
    assert grant['algorithm'] == 'OPENCV_SFACE_YUNET_V1'


def test_administrator_metadata_has_no_image_and_device_cannot_read_it(face):
    registration = face['catalog']['employee']['registration']
    reply = success(face['admin'].get(P + '/face-reference', params={'registration': registration}))
    assert reply['has_reference'] is True
    assert reply['employee_id'] == face['catalog']['employee']['id']
    assert not {'encrypted_image', 'image_base64', 'embedding', 'photo_url'} & set(reply)
    assert face['client'].get(P + '/face-reference', params={'registration': registration}).status_code == 401
    assert face['client'].post(P + '/face-reference', json=reference_body(face)).status_code == 401
    assert face['client'].delete(P + '/face-reference', params={'registration': registration}).status_code == 401
    for path in ('/records', '/employee/1', '/worksite/1'):
        assert face['client'].get(P + path).status_code == 401


@pytest.mark.parametrize('role', ['OPERADOR', 'CONSULTA'])
def test_non_administrative_roles_cannot_manage_references(face, role):
    success(face['admin'].post('/api/users', json={
        'name': 'Conta fictícia ' + role, 'username': role.lower(),
        'password': ADMIN_PASSWORD, 'role': role,
    }), 201)
    client = face['factory']()
    success(client.post('/api/auth/login', json={'username': role.lower(), 'password': ADMIN_PASSWORD}))
    registration = face['catalog']['employee']['registration']
    assert client.get(P + '/face-reference', params={'registration': registration}).status_code == 403
    assert client.post(P + '/face-reference', json=reference_body(face)).status_code == 403
    assert client.delete(P + '/face-reference', params={'registration': registration}).status_code == 403
    assert client.post(P + '/face-references/purge-expired').status_code == 403


def test_admin_history_unifies_simulated_and_facial_originals(face, monkeypatch):
    token = success(verify(face), 201)['authorization']
    success(mark(face, token), 201)
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'demo')
    demo = success(face['client'].post(P + '/terminal/test-authorizations', json={
        'registration': face['catalog']['employee']['registration'],
        'acknowledgement': 'TESTE_SUPERVISIONADO',
    }), 201)
    success(mark(face, demo['authorization'], kind='SAIDA'), 201)
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'facial')
    result = success(face['admin'].get(P + '/records'))
    assert result['total'] == 2
    assert {row['verification_method'] for row in result['items']} == {'DEMO_SUPERVISIONADO', 'FACIAL_EXPERIMENTAL'}
    assert len({row['record_uid'] for row in result['items']}) == 2
    employee_history = success(face['admin'].get(P + f"/employee/{face['catalog']['employee']['id']}"))
    assert employee_history['total'] == 2
    work_history = success(face['admin'].get(P + f"/worksite/{face['catalog']['work']['id']}"))
    assert work_history['total'] == 2


def test_comparison_mismatch_does_not_issue_authorization(face):
    face['engine'].matches = False
    response = verify(face)
    assert response.status_code == 403
    assert rows('attendance_face_grants') == []
    assert rows('attendance_authorizations') == []
    assert rows('attendance_facial_records') == []
    assert face['catalog']['employee']['name'] not in response.text


@pytest.mark.parametrize('code', ['no_face', 'multiple_faces', 'invalid_image'])
def test_invalid_face_image_is_rejected_without_grant_or_image_echo(face, code):
    from app.attendance.face_engine import FaceError
    face['engine'].error = FaceError(code, 'Imagem de teste recusada.', status_code=422)
    response = verify(face)
    assert response.status_code == 422
    assert IMAGE not in response.text and PREPARED.decode() not in response.text
    assert rows('attendance_face_grants') == []
    assert rows('attendance_authorizations') == []


def test_missing_inactive_wrong_work_and_mismatch_have_same_generic_reply(face):
    face['engine'].matches = False
    replies = [verify(face), verify(face, registration='NONEXISTENT-PRIVATE-REGISTRATION')]
    employee = face['catalog']['employee']
    with connect(write=True) as db:
        db.execute("UPDATE employees SET status='INATIVO' WHERE id=?", (employee['id'],))
    replies.append(verify(face))
    with connect(write=True) as db:
        db.execute("UPDATE employees SET status='ATIVO',work_id=? WHERE id=?", (face['catalog']['other_work']['id'], employee['id']))
    replies.append(verify(face))
    assert all(reply.status_code == 403 for reply in replies)
    assert len({reply.text for reply in replies}) == 1
    assert employee['name'] not in replies[0].text


def test_reference_missing_or_expired_cannot_be_verified(face):
    with connect(write=True) as db:
        db.execute("UPDATE attendance_face_references SET expires_at='2000-01-01T00:00:00+00:00'")
    assert verify(face).status_code == 403
    success(face['admin'].delete(P + '/face-reference', params={'registration': face['catalog']['employee']['registration']}))
    assert verify(face).status_code == 403
    assert rows('attendance_face_grants') == []


@pytest.mark.parametrize('action', ['replace', 'delete'])
def test_reference_change_invalidates_unconsumed_grant(face, action):
    token = success(verify(face), 201)['authorization']
    original_version = rows('attendance_face_references')[0]['version_uid']
    if action == 'replace':
        success(upload(face), 201)
        assert rows('attendance_face_references')[0]['version_uid'] != original_version
    else:
        success(face['admin'].delete(P + '/face-reference', params={'registration': face['catalog']['employee']['registration']}))
        assert rows('attendance_face_references') == []
    assert mark(face, token).status_code in (403, 409)
    assert rows('attendance_facial_records') == []


@pytest.mark.parametrize('change_kind', ['employee', 'reference', 'terminal'])
def test_employee_or_reference_changed_while_comparison_runs_cannot_issue_grant(face, change_kind):
    def change():
        with connect(write=True) as db:
            if change_kind == 'employee':
                db.execute("UPDATE employees SET status='INATIVO' WHERE id=?", (face['catalog']['employee']['id'],))
            elif change_kind == 'reference':
                db.execute('UPDATE attendance_face_references SET version_uid=? WHERE employee_id=?',
                           (str(uuid.uuid4()), face['catalog']['employee']['id']))
            else:
                db.execute('UPDATE attendance_terminals SET active=0 WHERE id=?', (face['terminal']['id'],))
    face['engine'].before_compare = change
    assert verify(face).status_code == 403
    assert rows('attendance_face_grants') == []


def test_deleted_reference_does_not_remove_confirmed_original_or_idempotent_receipt(face):
    token, key = success(verify(face), 201)['authorization'], str(uuid.uuid4())
    first = success(mark(face, token, key), 201)
    success(face['admin'].delete(P + '/face-reference', params={'registration': face['catalog']['employee']['registration']}))
    assert success(mark(face, token, key), 201) == first
    assert len(rows('attendance_facial_records')) == 1
    assert rows('attendance_face_references') == []


def test_single_use_expiry_and_payload_idempotency(face):
    token, key = success(verify(face), 201)['authorization'], str(uuid.uuid4())
    first = success(mark(face, token, key), 201)
    assert success(mark(face, token, key), 201) == first
    assert mark(face, token, key, kind='SAIDA').status_code == 409
    assert mark(face, token).status_code == 409
    with connect(write=True) as db:
        db.execute("UPDATE attendance_authorizations SET expires_at='2000-01-01T00:00:00+00:00'")
    assert success(mark(face, token, key), 201) == first
    fresh = success(verify(face), 201)['authorization']
    with connect(write=True) as db:
        db.execute("UPDATE attendance_authorizations SET expires_at='2000-01-01T00:00:00+00:00'")
    assert mark(face, fresh).status_code == 409
    assert len(rows('attendance_facial_records')) == 1


def test_grant_cannot_move_to_another_device_or_work(face):
    token = success(verify(face), 201)['authorization']
    terminal = success(face['admin'].post(P + '/terminals', json={
        'name': 'Segundo terminal fictício', 'work_id': face['catalog']['other_work']['id'],
    }), 201)
    code = success(face['admin'].post(P + f"/terminals/{terminal['id']}/activation"), 201)['activation_code']
    other = face['factory']()
    success(other.post(P + '/terminal/activate', json={'activation_code': code}), 201)
    assert mark({**face, 'client': other}, token).status_code == 403
    success(mark(face, token), 201)
    assert len(rows('attendance_facial_records')) == 1


def test_concurrent_replay_commits_only_one_facial_record(face):
    token, key, barrier = success(verify(face), 201)['authorization'], str(uuid.uuid4()), Barrier(2)
    def call(_):
        client = face['factory']()
        client.cookies.update(face['client'].cookies)
        barrier.wait(timeout=10)
        return mark({**face, 'client': client}, token, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(call, (1, 2)))
    assert all(reply.status_code == 201 for reply in replies)
    assert replies[0].json() == replies[1].json()
    assert len(rows('attendance_facial_records')) == 1


def test_different_legitimate_close_marks_are_preserved(face):
    for kind in ('ENTRADA', 'SAIDA'):
        success(mark(face, success(verify(face), 201)['authorization'], kind=kind), 201)
    assert len(rows('attendance_facial_records')) == 2


@pytest.mark.parametrize('extra', [
    {'face_verified': True}, {'marked_at': '2000-01-01'}, {'work_id': 2},
    {'terminal_id': 2}, {'image_base64': IMAGE},
])
def test_mark_cannot_accept_client_identity_image_or_clock(face, extra):
    token = success(verify(face), 201)['authorization']
    assert mark(face, token, **extra).status_code == 422
    assert rows('attendance_facial_records') == []


@pytest.mark.parametrize('extra', [{'face_verified': True}, {'work_id': 2}, {'terminal_id': 2}, {'marked_at': '2000-01-01'}])
def test_verify_payload_strict_and_validation_errors_do_not_echo_image(face, extra):
    reply = verify(face, **extra)
    assert reply.status_code == 422
    assert IMAGE not in reply.text
    assert rows('attendance_face_grants') == []


def test_reference_requires_explicit_authorization_basis_and_bounded_retention(face):
    before = rows('attendance_face_references')
    for extra in ({'acknowledgement': 'YES'}, {'authorization_basis': ''}, {'authorization_basis': ' ' * 20 + 'x'}, {'retention_days': 0}, {'retention_days': 91}, {'unknown': IMAGE}):
        response = upload(face, **extra)
        assert response.status_code == 422
        assert IMAGE not in response.text
    assert rows('attendance_face_references') == before


def test_json_image_endpoints_reject_malformed_and_oversized_input_safely(face):
    for client, endpoint in ((face['client'], '/terminal/verify-face'), (face['admin'], '/face-reference')):
        malformed = client.post(P + endpoint, content='{"image_base64":"' + IMAGE, headers={'Content-Type': 'application/json'})
        assert malformed.status_code == 422
        assert IMAGE not in malformed.text
        oversized = client.post(P + endpoint, content='x' * (3 * 1024 * 1024 + 1), headers={'Content-Type': 'application/json'})
        assert oversized.status_code == 413
        assert len(oversized.content) < 2000


def test_wrong_encryption_key_fails_closed_and_reference_can_still_be_deleted(face, monkeypatch):
    monkeypatch.setenv('COMPAC_FACE_KEY', base64.urlsafe_b64encode(b'x' * 32).decode())
    response = verify(face)
    assert response.status_code == 503
    assert PREPARED.decode() not in response.text and IMAGE not in response.text
    assert rows('attendance_face_grants') == []
    success(face['admin'].delete(P + '/face-reference', params={'registration': face['catalog']['employee']['registration']}))
    assert rows('attendance_face_references') == []


@pytest.mark.parametrize('operation', ['reference', 'verification', 'mark'])
def test_audit_failure_rolls_back_every_facial_operation(face, operation):
    token = success(verify(face), 201)['authorization'] if operation == 'mark' else None
    tables = ('attendance_face_references', 'attendance_face_grants', 'attendance_authorizations', 'attendance_facial_records', 'idempotency_requests')
    before = {table: rows(table) for table in tables}
    owner = face['admin'] if operation == 'reference' else face['client']
    key = str(uuid.uuid4())
    with TestClient(owner.app, base_url='https://testserver', headers={'X-Compac-Client': 'web'}, raise_server_exceptions=False) as client:
        client.cookies.update(owner.cookies)
        test_face = {**face, 'admin' if operation == 'reference' else 'client': client}
        with patch.object(service, 'emit_audit', side_effect=RuntimeError('Injected facial transaction failure')):
            response = upload(test_face) if operation == 'reference' else verify(test_face) if operation == 'verification' else mark(test_face, token, key)
            assert response.status_code == 500
    assert {table: rows(table) for table in tables} == before
    retry = upload(face) if operation == 'reference' else verify(face) if operation == 'verification' else mark(face, token, key)
    success(retry, 201)


def test_failed_comparisons_are_rate_limited_without_creating_grants(face):
    face['engine'].matches = False
    replies = []
    for _ in range(61):
        reply = verify(face)
        replies.append(reply)
        if reply.status_code == 429:
            break
        assert reply.status_code == 403
    assert replies[-1].status_code == 429
    assert replies[-1].headers.get('Retry-After')
    assert rows('attendance_face_grants') == []


def test_demo_and_facial_grants_cannot_cross_modes(face, monkeypatch):
    facial_token = success(verify(face), 201)['authorization']
    assert face['client'].post(P + '/terminal/test-authorizations', json={
        'registration': face['catalog']['employee']['registration'], 'acknowledgement': 'TESTE_SUPERVISIONADO',
    }).status_code == 404
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'demo')
    assert mark(face, facial_token).status_code == 403
    demo_token = success(face['client'].post(P + '/terminal/test-authorizations', json={
        'registration': face['catalog']['employee']['registration'], 'acknowledgement': 'TESTE_SUPERVISIONADO',
    }), 201)['authorization']
    monkeypatch.setenv('COMPAC_ATTENDANCE_MODE', 'facial')
    assert mark(face, demo_token).status_code == 403
    assert rows('attendance_facial_records') == []
    assert rows('attendance_records') == []


@pytest.mark.parametrize('variable,value,status', [('COMPAC_FACE_SUPERVISED', '0', 503), ('RENDER', 'true', 404), ('COMPAC_ENV', 'production', 404)])
def test_unsupervised_or_production_settings_block_verification(face, monkeypatch, variable, value, status):
    monkeypatch.setenv(variable, value)
    assert verify(face).status_code == status
    assert upload(face).status_code == status
    assert rows('attendance_face_grants') == []


def test_revoked_terminal_denies_verification_and_existing_grant(face):
    token = success(verify(face), 201)['authorization']
    success(face['admin'].post(P + f"/terminals/{face['terminal']['id']}/revoke"))
    assert verify(face).status_code == 403
    assert mark(face, token).status_code == 403
    assert rows('attendance_facial_records') == []


def test_reference_deletion_audit_failure_preserves_reference_and_unused_grant(face):
    token = success(verify(face), 201)['authorization']
    registration = face['catalog']['employee']['registration']
    tables = ('attendance_face_references', 'attendance_face_grants', 'attendance_authorizations')
    before = {table: rows(table) for table in tables}
    with TestClient(face['admin'].app, base_url='https://testserver',
                    headers={'X-Compac-Client': 'web'}, raise_server_exceptions=False) as client:
        client.cookies.update(face['admin'].cookies)
        with patch.object(service, 'emit_audit', side_effect=RuntimeError('Injected deletion audit failure')):
            response = client.delete(P + '/face-reference', params={'registration': registration})
            assert response.status_code == 500
    assert {table: rows(table) for table in tables} == before
    success(mark(face, token), 201)


def test_reference_upload_revalidates_administrator_after_image_processing(face):
    before = rows('attendance_face_references')
    def expire_admin_session(_):
        with connect(write=True) as db:
            db.execute('DELETE FROM sessions')
        return PREPARED
    with patch.object(face['engine'], 'prepare_reference', side_effect=expire_admin_session):
        assert upload(face).status_code == 401
    assert rows('attendance_face_references') == before


def test_device_rotation_during_comparison_cannot_issue_grant(face):
    def rotate():
        success(face['admin'].post(P + f"/terminals/{face['terminal']['id']}/activation"), 201)
    face['engine'].before_compare = rotate
    assert verify(face).status_code == 401
    assert rows('attendance_face_grants') == []
    assert rows('attendance_authorizations') == []


def test_invalid_capture_does_not_reveal_reference_or_employee_status_and_consumes_quota(face):
    from app.attendance.face_engine import FaceError
    face['engine'].error = FaceError('no_face', 'Nenhum rosto na imagem de teste.', 422)
    before = len(rows('auth_attempts'))
    replies = [verify(face), verify(face, registration='UNKNOWN-PRIVATE-REGISTRATION')]
    with connect(write=True) as db:
        db.execute("UPDATE employees SET status='INATIVO' WHERE id=?", (face['catalog']['employee']['id'],))
    replies.append(verify(face))
    with connect(write=True) as db:
        db.execute("UPDATE employees SET status='ATIVO' WHERE id=?", (face['catalog']['employee']['id'],))
        db.execute('DELETE FROM attendance_face_references WHERE employee_id=?', (face['catalog']['employee']['id'],))
    replies.append(verify(face))
    assert all(reply.status_code == 422 for reply in replies)
    assert len({reply.text for reply in replies}) == 1
    assert len(rows('auth_attempts')) == before + len(replies)
    assert face['engine'].compare_calls == 0
    assert rows('attendance_face_grants') == []
    assert rows('attendance_authorizations') == []
    assert all(IMAGE not in reply.text for reply in replies)


def another_reference(face):
    employee = success(face['admin'].post('/api/catalog/employees', json={
        'registration': 'SECOND-FICTITIOUS-EMPLOYEE', 'name': 'Segunda pessoa fictícia',
        'job_title': 'Teste', 'work_id': face['catalog']['work']['id'], 'status': 'ATIVO',
    }), 201)
    success(upload(face, registration=employee['registration']), 201)
    return employee


def test_purge_expired_only_removes_expired_reference_and_preserves_original_records(face):
    token = success(verify(face), 201)['authorization']
    receipt = success(mark(face, token), 201)
    pending = success(verify(face), 201)['authorization']
    other = another_reference(face)
    before_records = rows('attendance_facial_records')
    with connect(write=True) as db:
        db.execute("UPDATE attendance_face_references SET expires_at='2000-01-01T00:00:00+00:00' WHERE employee_id=?",
                   (face['catalog']['employee']['id'],))
    assert face['client'].post(P + '/face-references/purge-expired').status_code == 401
    result = success(face['admin'].post(P + '/face-references/purge-expired'))
    assert result == {'deleted': 1, 'experimental': True}
    assert [row['employee_id'] for row in rows('attendance_face_references')] == [other['id']]
    assert rows('attendance_facial_records') == before_records
    assert mark(face, pending).status_code in (403, 409)
    grants = {row['token_hash']: row for row in rows('attendance_authorizations')}
    assert grants[hashlib.sha256(pending.encode()).hexdigest()]['used_at']
    history = success(face['admin'].get(P + '/records'))
    assert history['total'] == 1 and history['items'][0]['record_uid'] == receipt['record_uid']
    assert success(face['admin'].post(P + '/face-references/purge-expired'))['deleted'] == 0


def test_purge_audit_failure_rolls_back_all_references_and_grant_invalidation(face):
    token = success(verify(face), 201)['authorization']
    another_reference(face)
    with connect(write=True) as db:
        db.execute("UPDATE attendance_face_references SET expires_at='2000-01-01T00:00:00+00:00'")
    tables = ('attendance_face_references', 'attendance_authorizations', 'attendance_face_grants', 'audit')
    before = {table: rows(table) for table in tables}
    with TestClient(face['admin'].app, base_url='https://testserver',
                    headers={'X-Compac-Client': 'web'}, raise_server_exceptions=False) as client:
        client.cookies.update(face['admin'].cookies)
        with patch.object(service, 'emit_audit', side_effect=[None, RuntimeError('Injected second purge audit failure')]):
            assert client.post(P + '/face-references/purge-expired').status_code == 500
    assert {table: rows(table) for table in tables} == before
    assert not next(row for row in rows('attendance_authorizations') if row['token_hash'] == hashlib.sha256(token.encode()).hexdigest())['used_at']
    assert success(face['admin'].post(P + '/face-references/purge-expired'))['deleted'] == 2


@pytest.mark.parametrize('operation', ['delete', 'purge'])
def test_reference_erasure_does_not_depend_on_models_or_encryption_key(face, monkeypatch, operation):
    from app.attendance import face_engine
    monkeypatch.setenv('COMPAC_FACE_KEY', '')
    with connect(write=True) as db:
        db.execute("UPDATE attendance_face_references SET expires_at='2000-01-01T00:00:00+00:00'")
    with patch.object(face_engine, 'get_engine', side_effect=face_engine.FaceError('unavailable', 'Modelo indisponível.', 503)) as engine:
        if operation == 'delete':
            response = face['admin'].delete(P + '/face-reference', params={'registration': face['catalog']['employee']['registration']})
        else:
            response = face['admin'].post(P + '/face-references/purge-expired')
        assert response.status_code == 200, response.text
        engine.assert_not_called()
    assert rows('attendance_face_references') == []
