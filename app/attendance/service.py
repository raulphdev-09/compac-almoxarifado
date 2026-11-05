"""Supervised test records only. No camera, image, face detector or matcher."""
import hashlib
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from ..security import failure_state, record_failure


AUTHORIZATION_SECONDS = 60
TEST_ATTEMPT_LIMIT = 30


def utcnow():
    return datetime.now(timezone.utc)


def demo_only():
    allowed = (
        os.getenv('COMPAC_ATTENDANCE_MODE', 'disabled') == 'demo'
        and os.getenv('COMPAC_ENV') in ('development', 'test')
        and os.getenv('RENDER', '').lower() != 'true'
    )
    if not allowed:
        raise HTTPException(404, 'Módulo experimental de ponto desativado neste ambiente.')
    url = os.getenv('DATABASE_URL', '').strip()
    if url:
        from ..db import postgres_options
        if postgres_options(url).get('host') not in ('localhost', '127.0.0.1', '::1'):
            raise HTTPException(404, 'Demonstração permitida somente em banco local descartável.')


def emit_audit(db, user_id, action, entity, record_id=None, details=None):
    # Lazy import avoids coupling module initialization to the application router.
    from ..main import audit
    audit(db, user_id, action, entity, record_id, details)


def row(db, table, key):
    result = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
    if not result:
        raise HTTPException(404, 'Registro de teste não encontrado.')
    return result


def checked_terminal(db, terminal_id):
    terminal = row(db, 'attendance_terminals', terminal_id)
    if not terminal['active']:
        raise HTTPException(403, 'Terminal de teste revogado.')
    work = row(db, 'works', terminal['work_id'])
    if work['status'] != 'ATIVA':
        raise HTTPException(409, 'A obra está inativa.')
    return terminal


def checked_employee(db, employee_id, terminal):
    employee = row(db, 'employees', employee_id)
    if employee['status'] != 'ATIVO':
        raise HTTPException(409, 'Funcionário inativo.')
    if employee['work_id'] != terminal['work_id']:
        raise HTTPException(403, 'Funcionário não vinculado à obra deste terminal.')
    return employee


def rate_attempt(db, actor_id, terminal_id, origin):
    account = hashlib.sha256(f'attendance-demo\0actor\0{actor_id}'.encode()).hexdigest()
    source = hashlib.sha256(f'attendance-demo\0origin\0{terminal_id}\0{origin}'.encode()).hexdigest()
    state = failure_state(db, account, source)
    if state[1] >= TEST_ATTEMPT_LIMIT or state[2] >= TEST_ATTEMPT_LIMIT:
        raise HTTPException(429, 'Limite de testes atingido. Aguarde cinco minutos.', headers={'Retry-After': '300'})
    record_failure(db, account, source, int(time.time()))


def authorize_test(db, payload, user, origin):
    rate_attempt(db, user['id'], payload.terminal_id, origin)
    terminal = checked_terminal(db, payload.terminal_id)
    employee = db.execute('SELECT id FROM employees WHERE LOWER(registration)=LOWER(?)', (payload.registration,)).fetchone()
    if not employee:
        raise HTTPException(404, 'Funcionário de teste não encontrado.')
    employee = checked_employee(db, employee['id'], terminal)
    secret = secrets.token_urlsafe(32)
    created = utcnow()
    expiry = created + timedelta(seconds=AUTHORIZATION_SECONDS)
    db.execute('INSERT INTO attendance_authorizations(token_hash,employee_id,terminal_id,created_by,created_at,expires_at) VALUES(?,?,?,?,?,?)',
               (hashlib.sha256(secret.encode()).hexdigest(), employee['id'], terminal['id'], user['id'], created.isoformat(), expiry.isoformat()))
    emit_audit(db, user['id'], 'PONTO_TESTE_AUTORIZADO', 'attendance_terminals', terminal['id'],
               {'employee_id': employee['id'], 'work_id': terminal['work_id'], 'method': 'DEMO_SUPERVISIONADO'})
    return {'authorization': secret, 'expires_at': expiry.isoformat(), 'expires_in': AUTHORIZATION_SECONDS,
            'experimental': True, 'verification_method': 'DEMO_SUPERVISIONADO', 'verification_result': 'SIMULADO'}


def mark_test(db, payload, user, origin):
    fingerprint = hashlib.sha256(payload.authorization.encode()).hexdigest()
    authorization = db.execute('SELECT * FROM attendance_authorizations WHERE token_hash=?', (fingerprint,)).fetchone()
    rate_attempt(db, user['id'], authorization['terminal_id'] if authorization else 0, origin)
    if not authorization or authorization['created_by'] != user['id']:
        raise HTTPException(403, 'Autorização de teste inválida.')
    if authorization['used_at']:
        raise HTTPException(409, 'Autorização já utilizada.')
    timestamp = utcnow().isoformat()
    if authorization['expires_at'] <= timestamp:
        raise HTTPException(409, 'Autorização de teste expirada.')
    terminal = checked_terminal(db, authorization['terminal_id'])
    checked_employee(db, authorization['employee_id'], terminal)
    uid = str(uuid.uuid4())
    key = db.execute('INSERT INTO attendance_records(record_uid,employee_id,work_id,terminal_id,mark_type,marked_at,verification_method,verification_result,is_test,created_by,authorization_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id',
                     (uid, authorization['employee_id'], terminal['work_id'], terminal['id'], payload.mark_type, timestamp,
                      'DEMO_SUPERVISIONADO', 'SIMULADO', 1, user['id'], fingerprint)).fetchone()['id']
    db.execute('UPDATE attendance_authorizations SET used_at=? WHERE token_hash=?', (timestamp, fingerprint))
    emit_audit(db, user['id'], 'PONTO_TESTE_MARCADO', 'attendance_records', key,
               {'employee_id': authorization['employee_id'], 'work_id': terminal['work_id'], 'terminal_id': terminal['id'],
                'mark_type': payload.mark_type, 'method': 'DEMO_SUPERVISIONADO'})
    return public_record(row(db, 'attendance_records', key))


def public_record(record):
    # Authorization hashes are internal and never part of record responses.
    return {k: record[k] for k in ('id', 'record_uid', 'employee_id', 'work_id', 'terminal_id', 'mark_type',
                                  'marked_at', 'verification_method', 'verification_result', 'is_test', 'created_by')}
