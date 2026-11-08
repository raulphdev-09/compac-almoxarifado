"""Supervised, local facial experiment. Captures never enter persistent storage."""
import json
import os
import secrets
import uuid
from datetime import timedelta
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from ..db import connect
from . import face_engine, service
from .device import (admin_in_transaction, credential_rate, device_in_transaction,
                     digest, response_error, secure_transport)
from .schemas import StrictPayload


ALGORITHM = 'OPENCV_SFACE_YUNET_V1'
MAX_BODY = 3 * 1024 * 1024
DENIED = 'Não foi possível confirmar a identidade neste terminal. Procure o supervisor.'


class ReferenceInput(StrictPayload):
    registration: str = Field(min_length=1, max_length=120)
    image_base64: str = Field(min_length=1, max_length=2800000)
    authorization_basis: str = Field(min_length=20, max_length=500)
    retention_days: int = Field(ge=1, le=90)
    acknowledgement: Literal['AUTORIZACAO_ORGANIZACIONAL_E_BASE_LEGAL_CONFIRMADAS']

    @field_validator('registration', 'authorization_basis')
    @classmethod
    def trimmed(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Preenchimento obrigatório.')
        return value

    @field_validator('authorization_basis')
    @classmethod
    def meaningful_basis(cls, value):
        if len(value) < 20:
            raise ValueError('Descreva a autorização e a base legal.')
        return value


class VerificationInput(StrictPayload):
    registration: str = Field(min_length=1, max_length=120)
    image_base64: str = Field(min_length=1, max_length=2800000)
    acknowledgement: Literal['VERIFICACAO_FACIAL_SUPERVISIONADA']

    @field_validator('registration')
    @classmethod
    def trimmed(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Matrícula obrigatória.')
        return value


def facial_only():
    service.experimental_only()
    if os.getenv('COMPAC_ATTENDANCE_MODE') != 'facial':
        raise HTTPException(404, 'Verificação facial desativada neste modo.')
    if os.getenv('COMPAC_FACE_SUPERVISED') != '1':
        raise HTTPException(503, 'Habilite o procedimento de teste supervisionado no servidor.')


async def private_payload(request, schema):
    """Bound memory and never echo biometric input in Pydantic error responses."""
    if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
        raise HTTPException(415, 'Envie JSON com imagem JPEG ou PNG em base64.')
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise HTTPException(413, 'Imagem excede o limite permitido.')
        chunks.append(chunk)
    try:
        data = json.loads(b''.join(chunks))
        return schema.model_validate(data)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise HTTPException(422, 'Dados inválidos. Confira os campos obrigatórios e os limites da imagem.')


def employee_by_registration(db, registration):
    return db.execute('SELECT * FROM employees WHERE LOWER(registration)=LOWER(?)', (registration,)).fetchone()


def reference_row(db, employee_id):
    row = db.execute('SELECT * FROM attendance_face_references WHERE employee_id=?', (employee_id,)).fetchone()
    return dict(row) if row else None


def metadata(db, employee):
    reference = reference_row(db, employee['id'])
    work = db.execute('SELECT name FROM works WHERE id=?', (employee['work_id'],)).fetchone()
    return {'employee_id': employee['id'], 'registration': employee['registration'], 'name': employee['name'],
            'work_name': work['name'] if work else '', 'has_reference': bool(reference),
            'reference_version': reference['version_uid'] if reference else None,
            'expires_at': reference['expires_at'] if reference else None, 'experimental': True}


def invalidate_reference_grants(db, version):
    if version:
        db.execute('UPDATE attendance_authorizations SET used_at=COALESCE(used_at,?) WHERE token_hash IN '
                   '(SELECT token_hash FROM attendance_face_grants WHERE reference_version=?)',
                   (service.utcnow().isoformat(), version))


def engine_call(operation):
    try:
        return operation()
    except face_engine.FaceError as exc:
        raise HTTPException(exc.status_code, exc.message)
    except Exception:
        # Native decoders/DNNs must not disclose data or paths in API errors.
        raise HTTPException(503, 'Verificação facial indisponível. Procure o supervisor.') from None


def upload_reference(data, request):
    with connect(write=True) as db:
        actor = admin_in_transaction(db, request)
        try:
            credential_rate(db, request, 'reference:' + str(actor['id']))
        except HTTPException as exc:
            return response_error(exc)
        employee = employee_by_registration(db, data.registration)
        if not employee:
            raise HTTPException(404, 'Funcionário não encontrado.')
        if employee['status'] != 'ATIVO':
            raise HTTPException(409, 'A referência exige funcionário ativo.')
        employee_id = employee['id']
    # Decode/detect outside the global database writer lock.
    image = engine_call(lambda: face_engine.get_engine().prepare_reference(data.image_base64))
    version = str(uuid.uuid4())
    encrypted = engine_call(lambda: face_engine.encrypt_reference(image, employee_id, version))
    del image
    with connect(write=True) as db:
        actor = admin_in_transaction(db, request)
        employee = employee_by_registration(db, data.registration)
        if not employee or employee['id'] != employee_id or employee['status'] != 'ATIVO':
            raise HTTPException(409, 'Cadastro alterado durante o envio. Confira e tente novamente.')
        previous = reference_row(db, employee_id)
        invalidate_reference_grants(db, previous['version_uid'] if previous else None)
        now = service.utcnow()
        db.execute('INSERT INTO attendance_face_references(employee_id,version_uid,encrypted_image,authorized_by,authorization_basis,created_at,expires_at) '
                   'VALUES(?,?,?,?,?,?,?) ON CONFLICT(employee_id) DO UPDATE SET version_uid=excluded.version_uid,encrypted_image=excluded.encrypted_image,'
                   'authorized_by=excluded.authorized_by,authorization_basis=excluded.authorization_basis,created_at=excluded.created_at,expires_at=excluded.expires_at',
                   (employee_id, version, encrypted, actor['id'], data.authorization_basis.strip(), now.isoformat(),
                    (now + timedelta(days=data.retention_days)).isoformat()))
        service.emit_audit(db, actor['id'], 'PONTO_REFERENCIA_ATUALIZADA', 'employees', employee_id,
                           {'reference_version': version, 'retention_days': data.retention_days})
        return metadata(db, employee)


def verification_snapshot(db, request, registration):
    device, terminal, actor = device_in_transaction(db, request)
    employee = employee_by_registration(db, registration)
    try:
        if not employee:
            raise HTTPException(403, DENIED)
        employee = service.checked_employee(db, employee['id'], terminal)
        reference = reference_row(db, employee['id'])
        if not reference or reference['expires_at'] <= service.utcnow().isoformat():
            raise HTTPException(403, DENIED)
    except HTTPException:
        raise HTTPException(403, DENIED)
    return device, terminal, actor, employee, reference


def verify_face(data, request):
    # Persist quota first, including rejected employees/images and native failures.
    with connect(write=True) as db:
        try:
            device, terminal, _ = device_in_transaction(db, request)
            credential_rate(db, request, 'face:' + str(terminal['id']))
        except HTTPException as exc:
            return response_error(exc)
    # Validate every capture before looking up a person. A blank/malformed
    # image must not distinguish an existing reference from an unknown worker.
    prepared_capture = engine_call(lambda: face_engine.get_engine().prepare_reference(data.image_base64))
    del prepared_capture
    with connect() as db:
        device, terminal, actor, employee, reference = verification_snapshot(db, request, data.registration)
        snapshot = (device['token_hash'], terminal['id'], terminal['work_id'], employee['id'], reference['version_uid'])
    image = engine_call(lambda: face_engine.decrypt_reference(reference['encrypted_image'], employee['id'], reference['version_uid']))
    confirmed = engine_call(lambda: face_engine.get_engine().compare(image, data.image_base64))
    del image
    if confirmed is not True:
        with connect(write=True) as db:
            device, terminal, actor = device_in_transaction(db, request)
            service.emit_audit(db, actor['id'], 'PONTO_FACE_NEGADA', 'attendance_terminals', terminal['id'],
                               {'result': 'NAO_CONFIRMADA'})
        raise HTTPException(403, DENIED)
    with connect(write=True) as db:
        # Revalidate after expensive inference: revocation/reference/work changes win.
        device, terminal, actor, employee, current = verification_snapshot(db, request, data.registration)
        if snapshot != (device['token_hash'], terminal['id'], terminal['work_id'], employee['id'], current['version_uid']):
            raise HTTPException(403, DENIED)
        secret = secrets.token_urlsafe(32)
        now = service.utcnow()
        expiry = now + timedelta(seconds=service.AUTHORIZATION_SECONDS)
        db.execute('INSERT INTO attendance_authorizations(token_hash,employee_id,terminal_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?)',
                   (digest(secret), employee['id'], terminal['id'], actor['id'], now.isoformat(), expiry.isoformat()))
        db.execute('INSERT INTO attendance_face_grants(token_hash,device_session_hash,reference_version,algorithm) VALUES(?,?,?,?)',
                   (digest(secret), device['token_hash'], current['version_uid'], ALGORITHM))
        service.emit_audit(db, actor['id'], 'PONTO_FACE_CONFIRMADA', 'attendance_terminals', terminal['id'],
                           {'employee_id': employee['id'], 'work_id': terminal['work_id'], 'method': 'FACIAL_EXPERIMENTAL'})
        return {'authorization': secret, 'expires_in': service.AUTHORIZATION_SECONDS, 'expires_at': expiry.isoformat(),
                'experimental': True, 'verification_method': 'FACIAL_EXPERIMENTAL', 'verification_result': 'CORRESPONDENCIA_CONFIRMADA'}


def mark_facial(db, data, actor, device, terminal):
    facial_only()
    fingerprint = digest(data.authorization)
    authorization = db.execute('SELECT * FROM attendance_authorizations WHERE token_hash=?', (fingerprint,)).fetchone()
    grant = db.execute('SELECT * FROM attendance_face_grants WHERE token_hash=?', (fingerprint,)).fetchone()
    if not authorization or not grant or authorization['created_by'] != actor['id'] or grant['device_session_hash'] != device['token_hash']:
        raise HTTPException(403, DENIED)
    if authorization['terminal_id'] != terminal['id'] or grant['algorithm'] != ALGORITHM:
        raise HTTPException(403, DENIED)
    if authorization['used_at']:
        raise HTTPException(409, 'Autorização já utilizada ou invalidada. Procure o supervisor.')
    now = service.utcnow().isoformat()
    if authorization['expires_at'] <= now:
        raise HTTPException(409, 'Autorização facial expirada.')
    try:
        service.checked_employee(db, authorization['employee_id'], terminal)
        reference = reference_row(db, authorization['employee_id'])
        if not reference or reference['version_uid'] != grant['reference_version'] or reference['expires_at'] <= now:
            raise HTTPException(403, DENIED)
    except HTTPException:
        raise HTTPException(403, DENIED)
    uid = str(uuid.uuid4())
    key = db.execute('INSERT INTO attendance_facial_records(record_uid,employee_id,work_id,terminal_id,mark_type,marked_at,verification_method,verification_result,is_test,created_by,authorization_hash) '
                     'VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id',
                     (uid, authorization['employee_id'], terminal['work_id'], terminal['id'], data.mark_type, now,
                      'FACIAL_EXPERIMENTAL', 'CORRESPONDENCIA_CONFIRMADA', 1, actor['id'], fingerprint)).fetchone()['id']
    db.execute('UPDATE attendance_authorizations SET used_at=? WHERE token_hash=?', (now, fingerprint))
    service.emit_audit(db, actor['id'], 'PONTO_FACIAL_MARCADO', 'attendance_facial_records', key,
                       {'employee_id': authorization['employee_id'], 'work_id': terminal['work_id'], 'terminal_id': terminal['id'],
                        'mark_type': data.mark_type, 'method': 'FACIAL_EXPERIMENTAL'})
    return {'record_uid': uid, 'mark_type': data.mark_type, 'marked_at': now,
            'verification_result': 'CORRESPONDENCIA_CONFIRMADA', 'experimental': True}


def register_face_routes(app, administrator):
    prefix = '/api/v1/attendance'

    def admin_face(request: Request, user=Depends(administrator)):
        facial_only()
        secure_transport(request)
        return user

    def authenticated_device(request):
        with connect() as db:
            device_in_transaction(db, request)

    @app.get(prefix + '/face-reference')
    def get_reference(request: Request, registration: str = Query(min_length=1, max_length=120), user=Depends(admin_face)):
        with connect() as db:
            employee = employee_by_registration(db, registration.strip())
            if not employee:
                raise HTTPException(404, 'Funcionário não encontrado.')
            return metadata(db, employee)

    @app.post(prefix + '/face-reference', status_code=201)
    async def set_reference(request: Request, user=Depends(admin_face)):
        data = await private_payload(request, ReferenceInput)
        return await run_in_threadpool(upload_reference, data, request)

    @app.post(prefix + '/face-references/purge-expired')
    def purge_expired(request: Request, user=Depends(admin_face)):
        with connect(write=True) as db:
            actor = admin_in_transaction(db, request)
            expired = list(db.execute('SELECT employee_id,version_uid FROM attendance_face_references WHERE expires_at<=?',
                                      (service.utcnow().isoformat(),)))
            for reference in expired:
                invalidate_reference_grants(db, reference['version_uid'])
                db.execute('DELETE FROM attendance_face_references WHERE employee_id=? AND version_uid=?',
                           (reference['employee_id'], reference['version_uid']))
                service.emit_audit(db, actor['id'], 'PONTO_REFERENCIA_EXPIRADA_EXCLUIDA', 'employees', reference['employee_id'])
            return {'deleted': len(expired), 'experimental': True}

    @app.delete(prefix + '/face-reference')
    def delete_reference(request: Request, registration: str = Query(min_length=1, max_length=120), user=Depends(admin_face)):
        with connect(write=True) as db:
            actor = admin_in_transaction(db, request)
            employee = employee_by_registration(db, registration.strip())
            if not employee:
                raise HTTPException(404, 'Funcionário não encontrado.')
            reference = reference_row(db, employee['id'])
            invalidate_reference_grants(db, reference['version_uid'] if reference else None)
            db.execute('DELETE FROM attendance_face_references WHERE employee_id=?', (employee['id'],))
            service.emit_audit(db, actor['id'], 'PONTO_REFERENCIA_EXCLUIDA', 'employees', employee['id'])
            return metadata(db, employee)

    @app.post(prefix + '/terminal/verify-face', status_code=201)
    async def verify(request: Request):
        facial_only()
        secure_transport(request)
        # Reject an unauthenticated terminal before even reading a large image.
        await run_in_threadpool(authenticated_device, request)
        data = await private_payload(request, VerificationInput)
        return await run_in_threadpool(verify_face, data, request)
