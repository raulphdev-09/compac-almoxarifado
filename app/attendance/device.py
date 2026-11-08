"""Scoped terminal credentials for supervised experimental attendance."""
import hashlib
import os
import secrets
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from ..db import connect
from ..idempotency import replay_or_execute, validate_key
from ..security import failure_state, record_failure
from . import service
from .schemas import StrictPayload, TestAuthorizationInput, MarkInput


COOKIE = 'compac_attendance_terminal'
COOKIE_PATH = '/api/v1/attendance/terminal'
SESSION_SECONDS = 12 * 60 * 60
ACTIVATION_SECONDS = 600


class ActivationInput(StrictPayload):
    activation_code: str = Field(min_length=32, max_length=128)


class DeviceAuthorizationInput(StrictPayload):
    registration: str = Field(min_length=1, max_length=120)
    acknowledgement: Literal['TESTE_SUPERVISIONADO']

    @field_validator('registration')
    @classmethod
    def clean_registration(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Informe uma matrícula de teste.')
        return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def secure_transport(request):
    # A configured TLS terminator is trusted only through server configuration,
    # never through client-controlled forwarding headers.
    configured = os.getenv('COMPAC_PUBLIC_URL', '')
    proxy_tls = os.getenv('COMPAC_COOKIE_SECURE') == '1' and urlsplit(configured).scheme == 'https'
    local_hosts = ('localhost', '127.0.0.1', '::1')
    loopback = request.url.hostname in local_hosts and request.client and request.client.host in local_hosts
    if request.url.scheme != 'https' and not proxy_tls and not loopback:
        raise HTTPException(426, 'O terminal exige HTTPS. HTTP é permitido somente em localhost.')


def admin_in_transaction(db, request):
    row = db.execute('SELECT u.id,u.role FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1',
                     (digest(request.cookies.get('compac_session', '')), service.utcnow().isoformat())).fetchone()
    if not row:
        raise HTTPException(401, 'Entre com uma conta administrativa.')
    if row['role'] != 'ADMIN':
        raise HTTPException(403, 'Ação restrita a administrador.')
    return dict(row)


def device_in_transaction(db, request):
    secret = request.cookies.get(COOKIE, '')
    if not secret or len(secret) > 128:
        raise HTTPException(401, 'Ative este dispositivo com um código administrativo.')
    device = db.execute('SELECT * FROM attendance_device_sessions WHERE token_hash=?', (digest(secret),)).fetchone()
    if not device or device['revoked_at'] or device['expires_at'] <= service.utcnow().isoformat():
        raise HTTPException(401, 'Acesso do dispositivo expirado ou revogado. Solicite uma nova ativação.')
    try:
        terminal = service.checked_terminal(db, device['terminal_id'])
        issuer = service.row(db, 'users', device['created_by'])
        if not issuer['active'] or issuer['role'] != 'ADMIN':
            raise HTTPException(403, 'Administrador emissor inativo.')
    except HTTPException:
        raise HTTPException(403, 'Dispositivo ou obra indisponível. Solicite uma nova ativação.')
    return dict(device), terminal, {'id': issuer['id'], 'role': issuer['role']}


def terminal_public(db, terminal):
    facial = os.getenv('COMPAC_ATTENDANCE_MODE') == 'facial'
    if facial:
        from .face_engine import face_configuration
        configuration = face_configuration()
        ready = configuration['ready'] and os.getenv('COMPAC_FACE_SUPERVISED') == '1'
    else:
        ready = False
    return {'paired': True, 'terminal_name': terminal['name'],
            'work_name': service.row(db, 'works', terminal['work_id'])['name'],
            'server_time': service.utcnow().isoformat(), 'experimental': True,
            'time_zone': os.getenv('COMPAC_TIMEZONE', 'America/Sao_Paulo'),
            'mode': 'facial' if facial else 'demo', 'facial_recognition': facial,
            'face_ready': ready, 'supervised_only': True, 'anti_spoofing': False,
            'verification_result': 'PENDENTE' if facial else 'SIMULADO'}


def credential_rate(db, request, scope):
    source = request.client.host if request.client else 'unknown'
    account = digest('attendance-device\0' + scope + '\0' + source)
    origin = digest('attendance-device-origin\0' + source)
    state = failure_state(db, account, origin)
    if state[1] >= 30 or state[2] >= 60:
        raise HTTPException(429, 'Muitas tentativas. Aguarde cinco minutos.', headers={'Retry-After': '300'})
    record_failure(db, account, origin, state[0])


def response_error(exc):
    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=exc.headers)


def transactional_attempt(db, operation):
    db.execute('SAVEPOINT terminal_business')
    try:
        result = operation()
        db.execute('RELEASE SAVEPOINT terminal_business')
        return result
    except HTTPException as exc:
        db.execute('ROLLBACK TO SAVEPOINT terminal_business')
        db.execute('RELEASE SAVEPOINT terminal_business')
        return response_error(exc)


def register_device_routes(app, administrator):
    prefix = '/api/v1/attendance'

    def admin_demo(request: Request, user=Depends(administrator)):
        service.experimental_only()
        secure_transport(request)
        return user

    @app.post(prefix + '/terminals/{key}/activation', status_code=201)
    def activation_code(key: int, request: Request, user=Depends(admin_demo)):
        with connect(write=True) as db:
            admin_in_transaction(db, request)
            service.checked_terminal(db, key)
            now = service.utcnow()
            # Issuing a new code is an explicit rotation, never a silent retry.
            db.execute('UPDATE attendance_activation_codes SET used_at=COALESCE(used_at,?) WHERE terminal_id=?', (now.isoformat(), key))
            db.execute('UPDATE attendance_device_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE terminal_id=?', (now.isoformat(), key))
            code = secrets.token_urlsafe(32)
            db.execute('INSERT INTO attendance_activation_codes(token_hash,terminal_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?)',
                       (digest(code), key, user['id'], now.isoformat(), (now + timedelta(seconds=ACTIVATION_SECONDS)).isoformat()))
            service.emit_audit(db, user['id'], 'PONTO_ATIVACAO_EMITIDA', 'attendance_terminals', key)
        return {'activation_code': code, 'expires_in': ACTIVATION_SECONDS, 'experimental': True}

    @app.post(prefix + '/terminal/activate', status_code=201)
    def activate(data: ActivationInput, request: Request):
        service.experimental_only()
        secure_transport(request)
        with connect(write=True) as db:
            try:
                credential_rate(db, request, 'activation')
            except HTTPException as exc:
                return response_error(exc)

            def operation():
                code = db.execute('SELECT * FROM attendance_activation_codes WHERE token_hash=?', (digest(data.activation_code),)).fetchone()
                now = service.utcnow()
                if not code or code['used_at'] or code['expires_at'] <= now.isoformat():
                    raise HTTPException(401, 'Código de ativação inválido, usado ou expirado.')
                terminal = service.checked_terminal(db, code['terminal_id'])
                issuer = service.row(db, 'users', code['created_by'])
                if not issuer['active'] or issuer['role'] != 'ADMIN':
                    raise HTTPException(401, 'Código de ativação indisponível.')
                secret = secrets.token_urlsafe(32)
                db.execute('UPDATE attendance_device_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE token_hash=?',
                           (now.isoformat(), digest(request.cookies.get(COOKIE, ''))))
                db.execute('UPDATE attendance_activation_codes SET used_at=? WHERE token_hash=?', (now.isoformat(), code['token_hash']))
                db.execute('INSERT INTO attendance_device_sessions(token_hash,terminal_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?)',
                           (digest(secret), terminal['id'], issuer['id'], now.isoformat(), (now + timedelta(seconds=SESSION_SECONDS)).isoformat()))
                # A shared terminal must not inherit the administrator's session.
                db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(request.cookies.get('compac_session', '')),))
                service.emit_audit(db, issuer['id'], 'PONTO_DISPOSITIVO_ATIVADO', 'attendance_terminals', terminal['id'])
                response = JSONResponse(terminal_public(db, terminal), status_code=201)
                secure = request.url.scheme == 'https' or os.getenv('COMPAC_COOKIE_SECURE') == '1'
                response.set_cookie(COOKIE, secret, max_age=SESSION_SECONDS, path=COOKIE_PATH, httponly=True, secure=secure, samesite='strict')
                response.delete_cookie('compac_session')
                return response
            return transactional_attempt(db, operation)

    @app.get(prefix + '/terminal/status')
    def status(request: Request):
        service.experimental_only()
        secure_transport(request)
        with connect() as db:
            _, terminal, _ = device_in_transaction(db, request)
            return terminal_public(db, terminal)

    @app.post(prefix + '/terminal/test-authorizations', status_code=201)
    def authorize(data: DeviceAuthorizationInput, request: Request):
        service.demo_only()
        secure_transport(request)
        with connect(write=True) as db:
            try:
                device, terminal, actor = device_in_transaction(db, request)
                credential_rate(db, request, 'authorization:' + str(terminal['id']))
            except HTTPException as exc:
                return response_error(exc)

            def operation():
                try:
                    payload = TestAuthorizationInput(registration=data.registration, terminal_id=terminal['id'], acknowledgement=data.acknowledgement)
                    result = service.authorize_test(db, payload, actor, request.client.host if request.client else 'unknown')
                except HTTPException as exc:
                    if exc.status_code == 429:
                        raise
                    raise HTTPException(403, 'Não foi possível validar a matrícula neste terminal de teste.')
                db.execute('INSERT INTO attendance_device_authorizations(token_hash,device_session_hash) VALUES(?,?)',
                           (digest(result['authorization']), device['token_hash']))
                return result
            return transactional_attempt(db, operation)

    @app.post(prefix + '/terminal/mark', status_code=201)
    def mark(data: MarkInput, request: Request):
        service.experimental_only()
        facial = os.getenv('COMPAC_ATTENDANCE_MODE') == 'facial'
        if facial:
            from .face import facial_only, mark_facial
            facial_only()
        secure_transport(request)
        key = validate_key(request.headers.get('Idempotency-Key'))
        with connect(write=True) as db:
            try:
                device, terminal, actor = device_in_transaction(db, request)
            except HTTPException as exc:
                return response_error(exc)

            def operation():
                binding_table = 'attendance_face_grants' if facial else 'attendance_device_authorizations'
                binding = db.execute('SELECT device_session_hash FROM ' + binding_table + ' WHERE token_hash=?', (digest(data.authorization),)).fetchone()
                if not binding or binding['device_session_hash'] != device['token_hash']:
                    raise HTTPException(403, 'Autorização inválida para este dispositivo.')
                def commit():
                    credential_rate(db, request, 'mark:' + str(terminal['id']))
                    try:
                        result = mark_facial(db, data, actor, device, terminal) if facial else service.mark_test(db, data, actor, request.client.host if request.client else 'unknown')
                    except HTTPException as exc:
                        if exc.status_code in (403, 404):
                            raise HTTPException(403, 'Não foi possível registrar neste terminal de teste.')
                        raise
                    return {field: result[field] for field in ('record_uid', 'mark_type', 'marked_at', 'verification_result')} | {'experimental': True}
                return replay_or_execute(db, actor['id'], 'POST /terminal/mark:' + device['token_hash'], key, data.model_dump(), commit)
            result = transactional_attempt(db, operation)
            if isinstance(result, JSONResponse) and result.status_code >= 400:
                try:
                    credential_rate(db, request, 'mark-failure:' + str(terminal['id']))
                except HTTPException as exc:
                    return response_error(exc)
            return result

    @app.post(prefix + '/terminal/logout')
    def logout(request: Request):
        service.experimental_only()
        secure_transport(request)
        with connect(write=True) as db:
            token = digest(request.cookies.get(COOKIE, ''))
            device = db.execute('SELECT * FROM attendance_device_sessions WHERE token_hash=?', (token,)).fetchone()
            if device:
                db.execute('UPDATE attendance_device_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE token_hash=?', (service.utcnow().isoformat(), token))
                service.emit_audit(db, device['created_by'], 'PONTO_DISPOSITIVO_DESCONECTADO', 'attendance_terminals', device['terminal_id'])
        response = JSONResponse({'ok': True, 'experimental': True})
        response.delete_cookie(COOKIE, path=COOKIE_PATH)
        return response
