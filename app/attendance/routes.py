from datetime import date, datetime, time as day_time, timedelta, timezone
import hashlib
import os
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..db import connect
from ..idempotency import replay_or_execute, validate_key
from . import service
from .schemas import MarkInput, TerminalInput, TestAuthorizationInput


def register_attendance(app, administrator):
    prefix = '/api/v1/attendance'

    def supervised(user=Depends(administrator)):
        service.demo_only()
        return user

    def transaction_admin(db, request):
        token_hash = hashlib.sha256(request.cookies.get('compac_session', '').encode()).hexdigest()
        user = db.execute('SELECT u.id,u.role FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1',
                          (token_hash, service.utcnow().isoformat())).fetchone()
        if not user:
            raise HTTPException(401, 'Sessão encerrada. Entre novamente.')
        if user['role'] != 'ADMIN':
            raise HTTPException(403, 'Ação restrita a administrador.')

    def attempt(db, operation, user, request, terminal_hint=0):
        # An HTTP error must not commit a partly executed business operation.
        # Persist only the bounded attempt counter after rolling back its effects.
        db.execute('SAVEPOINT attendance_operation')
        try:
            result = operation()
            db.execute('RELEASE SAVEPOINT attendance_operation')
            return result
        except HTTPException as exc:
            db.execute('ROLLBACK TO SAVEPOINT attendance_operation')
            db.execute('RELEASE SAVEPOINT attendance_operation')
            try:
                service.rate_attempt(db, user['id'], terminal_hint, request.client.host if request.client else 'unknown')
            except HTTPException as rate_error:
                exc = rate_error
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.get(prefix + '/status')
    def module_status(user=Depends(administrator)):
        try:
            service.demo_only()
            enabled = True
        except HTTPException:
            enabled = False
        return {'enabled': enabled, 'phase': 1, 'experimental': True, 'facial_recognition': False,
                'terminal_authentication': False, 'mode': 'demo' if enabled else 'disabled'}

    @app.post(prefix + '/terminals', status_code=201)
    def create_terminal(data: TerminalInput, request: Request, user=Depends(supervised)):
        with connect(write=True) as db:
            transaction_admin(db, request)
            work = service.row(db, 'works', data.work_id)
            if work['status'] != 'ATIVA':
                raise HTTPException(409, 'A obra está inativa.')
            key = db.execute('INSERT INTO attendance_terminals(name,work_id,active,created_by,created_at) VALUES(?,?,1,?,?) RETURNING id',
                             (data.name, work['id'], user['id'], service.utcnow().isoformat())).fetchone()['id']
            service.emit_audit(db, user['id'], 'PONTO_TERMINAL_TESTE_CRIADO', 'attendance_terminals', key, {'work_id': work['id']})
            return dict(service.row(db, 'attendance_terminals', key))

    @app.get(prefix + '/terminals')
    def terminals(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), user=Depends(supervised)):
        with connect() as db:
            total = db.execute('SELECT COUNT(*) FROM attendance_terminals').fetchone()[0]
            items = [dict(r) for r in db.execute('SELECT * FROM attendance_terminals ORDER BY id LIMIT ? OFFSET ?', (limit, offset))]
        return {'items': items, 'total': total, 'limit': limit, 'offset': offset, 'experimental': True}

    @app.post(prefix + '/terminals/{key}/revoke')
    def revoke_terminal(key: int, request: Request, user=Depends(supervised)):
        with connect(write=True) as db:
            transaction_admin(db, request)
            service.row(db, 'attendance_terminals', key)
            db.execute('UPDATE attendance_terminals SET active=0,revoked_at=COALESCE(revoked_at,?) WHERE id=?', (service.utcnow().isoformat(), key))
            service.emit_audit(db, user['id'], 'PONTO_TERMINAL_TESTE_REVOGADO', 'attendance_terminals', key)
        return {'ok': True, 'experimental': True}

    @app.post(prefix + '/test-authorizations', status_code=201)
    def authorize(data: TestAuthorizationInput, request: Request, user=Depends(supervised)):
        with connect(write=True) as db:
            transaction_admin(db, request)
            return attempt(db, lambda: service.authorize_test(db, data, user, request.client.host if request.client else 'unknown'),
                           user, request, data.terminal_id)

    @app.post(prefix + '/mark', status_code=201)
    def mark(data: MarkInput, request: Request, user=Depends(supervised)):
        key = validate_key(request.headers.get('Idempotency-Key'))
        with connect(write=True) as db:
            transaction_admin(db, request)
            return attempt(db, lambda: replay_or_execute(db, user['id'], 'POST /api/v1/attendance/mark', key, data.model_dump(),
                                                        lambda: service.mark_test(db, data, user, request.client.host if request.client else 'unknown')),
                           user, request)

    def history(employee_id, work_id, mark_type, date_from, date_to, limit, offset):
        clauses, values = [], []
        for column, value in (('employee_id', employee_id), ('work_id', work_id), ('mark_type', mark_type)):
            if value is not None:
                clauses.append(column + '=?')
                values.append(value)
        if mark_type is not None and mark_type not in ('ENTRADA', 'INICIO_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA'):
            raise HTTPException(422, 'Tipo de marcação inválido.')
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, 'Período inválido.')
        tz = ZoneInfo(os.getenv('COMPAC_TIMEZONE', 'America/Sao_Paulo'))
        if date_from:
            clauses.append('marked_at>=?')
            values.append(datetime.combine(date_from, day_time.min, tzinfo=tz).astimezone(timezone.utc).isoformat())
        if date_to:
            clauses.append('marked_at<?')
            values.append(datetime.combine(date_to + timedelta(days=1), day_time.min, tzinfo=tz).astimezone(timezone.utc).isoformat())
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with connect() as db:
            total = db.execute('SELECT COUNT(*) FROM attendance_records' + where, tuple(values)).fetchone()[0]
            items = [service.public_record(r) for r in db.execute('SELECT * FROM attendance_records' + where + ' ORDER BY marked_at DESC,id DESC LIMIT ? OFFSET ?', (*values, limit, offset))]
        return {'items': items, 'total': total, 'limit': limit, 'offset': offset, 'has_more': offset + len(items) < total, 'experimental': True}

    @app.get(prefix + '/records')
    def records(employee_id: int | None = Query(None, gt=0), work_id: int | None = Query(None, gt=0), mark_type: str | None = None,
                date_from: date | None = None, date_to: date | None = None,
                limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), user=Depends(supervised)):
        return history(employee_id, work_id, mark_type, date_from, date_to, limit, offset)

    @app.get(prefix + '/employee/{key}')
    def employee_history(key: int, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), user=Depends(supervised)):
        return history(key, None, None, None, None, limit, offset)

    @app.get(prefix + '/worksite/{key}')
    def work_history(key: int, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000), user=Depends(supervised)):
        return history(None, key, None, None, None, limit, offset)
