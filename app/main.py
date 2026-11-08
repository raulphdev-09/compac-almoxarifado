import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .catalog import ENTITIES
from .db import connect, init_db
from .security import (
    FAILURE_WINDOW_SECONDS, credential_keys, failure_state, limited,
    mutation_origin_allowed, record_failure,
)

STATIC = Path(__file__).parent / 'static'
ROLES = ['ADMIN', 'OPERADOR', 'CONSULTA']
PRIORITIES = ['BAIXA', 'NORMAL', 'ALTA', 'URGENTE']


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(message, code=422):
    raise HTTPException(code, message)


def text(value, label, required=True, maximum=2000):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        fail(f'{label}: informe um texto.')
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        fail(f'{label}: preencha entre 1 e {maximum} caracteres.')
    return value


def number(value, label='Quantidade', minimum=0, places=3):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < Decimal(str(minimum)) or result > Decimal('1000000000'):
            raise ValueError
        if result != result.quantize(Decimal(10) ** -places):
            fail(f'{label}: use no máximo {places} casas decimais.')
        return result
    except (InvalidOperation, ValueError, TypeError):
        fail(f'{label}: informe um número válido a partir de {minimum}.')


def quantity(value, minimum=0.001):
    return int(number(value, minimum=minimum) * 1000)


def reference(db, table, value, optional=False):
    if value in (None, '') and optional:
        return None
    try:
        key = int(value)
        if isinstance(value, bool) or str(key) != str(value):
            raise ValueError
    except (ValueError, TypeError):
        fail('Selecione um registro válido.')
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
    if not row:
        fail('Registro vinculado não encontrado.', 404)
    return row


def active_reference(db, table, value):
    row = reference(db, table, value)
    if 'status' in row.keys() and row['status'] in ('INATIVO', 'INATIVA', 'CONCLUIDA', 'BAIXADO'):
        fail('O registro selecionado está inativo.')
    return row


def audit(db, user_id, action, entity, record_id=None, details=None):
    db.execute('INSERT INTO audit(user_id,action,entity,record_id,details,created_at) VALUES(?,?,?,?,?,?)',
               (user_id, action, entity, record_id, json.dumps(details or {}, ensure_ascii=False), now()))


def password(value):
    value = text(value, 'Senha', maximum=128)
    if len(value) < 10:
        fail('A senha deve conter pelo menos 10 caracteres.')
    return value


def hash_password(value):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()


def verify_password(value, encoded):
    salt, digest = encoded.split(':')
    derived = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(derived.hex(), digest)


def public_user(row):
    return {key: row[key] for key in ('id', 'username', 'name', 'role', 'active')}


def current_user(request: Request):
    token = hashlib.sha256(request.cookies.get('compac_session', '').encode()).hexdigest()
    with connect() as db:
        row = db.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1', (token, now())).fetchone()
    if not row:
        fail('Entre na sua conta para continuar.', 401)
    return public_user(row)


def operator(user=Depends(current_user)):
    if user['role'] == 'CONSULTA':
        fail('Seu perfil permite apenas consulta.', 403)
    return user


def administrator(user=Depends(current_user)):
    if user['role'] != 'ADMIN':
        fail('Esta ação exige um administrador.', 403)
    return user


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title='COMPAC • Almoxarifado', version='2.0.0', lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=STATIC), name='static')


@app.middleware('http')
async def security(request: Request, call_next):
    rejection = None
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        # Use a server-controlled public URL behind Render's TLS terminator.
        expected = (os.getenv('COMPAC_PUBLIC_URL') or os.getenv('RENDER_EXTERNAL_URL') or str(request.base_url)).rstrip('/')
        if not mutation_origin_allowed(request, expected):
            rejection = JSONResponse({'detail': 'Requisição de origem não autorizada.'}, status_code=403)
    response = rejection if rejection is not None else await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/ponto-facial'):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] += "; media-src 'self' blob:"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(psycopg.IntegrityError)
@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail': 'Código duplicado ou vínculo inválido. Confira os dados.'}, status_code=409)


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})


@app.get('/manifest.webmanifest', include_in_schema=False)
def manifest():
    return FileResponse(STATIC / 'manifest.webmanifest', media_type='application/manifest+json', headers={'Cache-Control': 'no-cache'})


@app.get('/sw.js', include_in_schema=False)
def worker():
    return FileResponse(STATIC / 'sw.js', media_type='application/javascript', headers={'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/'})


@app.get('/offline.html', include_in_schema=False)
def offline():
    return FileResponse(STATIC / 'offline.html', headers={'Cache-Control': 'no-cache'})


@app.get('/health')
def health():
    with connect() as db:
        db.execute('SELECT 1').fetchone()
    return {'status': 'ok'}


@app.get('/api/auth/status')
def auth_status():
    with connect() as db:
        missing = not bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())
    return {'needs_setup': missing, 'setup_token_required': missing and bool(os.getenv('COMPAC_SETUP_TOKEN'))}


def session_response(db, row):
    token = secrets.token_urlsafe(32)
    db.execute('DELETE FROM sessions WHERE expires_at<=?', (now(),))
    db.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id'], (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()))
    response = JSONResponse(public_user(row))
    response.set_cookie('compac_session', token, httponly=True, samesite='strict', secure=os.getenv('COMPAC_COOKIE_SECURE') == '1', max_age=28800)
    return response


@app.post('/api/auth/setup')
def setup(data: dict):
    with connect(write=True) as db:
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            fail('A configuração inicial já foi concluída.', 409)
        required = os.getenv('COMPAC_SETUP_TOKEN')
        supplied = data.get('setup_token', '')
        if required and (not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), required.encode())):
            fail('Código de ativação inválido.', 403)
        username = text(data.get('username'), 'Usuário', maximum=80)
        name = text(data.get('name'), 'Nome', maximum=120)
        hashed = hash_password(password(data.get('password')))
        key = db.execute('INSERT INTO users(username,name,password_hash,role,created_at) VALUES(?,?,?,?,?) RETURNING id', (username, name, hashed, 'ADMIN', now())).fetchone()['id']
        audit(db, key, 'CONFIGURACAO_INICIAL', 'users', key)
        return session_response(db, reference(db, 'users', key))


@app.post('/api/auth/login')
def login(data: dict, request: Request):
    username = text(data.get('username'), 'Usuário', maximum=80)
    value = text(data.get('password'), 'Senha', maximum=128)
    account_hash, origin_hash = credential_keys(username, request)
    with connect(write=True) as db:
        state = failure_state(db, account_hash, origin_hash)
        if limited(state):
            return credential_limit_response()
        row = db.execute('SELECT * FROM users WHERE LOWER(username)=LOWER(?) AND active=1', (username,)).fetchone()
        encoded = row['password_hash'] if row else '00'*16 + ':' + '00'*64
        if not verify_password(value, encoded) or row is None:
            failed_credential(db, account_hash, origin_hash, state, 'LOGIN_FALHOU')
            # Return a response instead of raising: failures and their audit
            # must commit even though authentication is rejected.
            return JSONResponse({'detail': 'Usuário ou senha inválidos.'}, status_code=401)
        audit(db, row['id'], 'LOGIN', 'users', row['id'])
        return session_response(db, row)


def credential_limit_response():
    return JSONResponse(
        {'detail': 'Muitas tentativas. Aguarde cinco minutos.'}, status_code=429,
        headers={'Retry-After': str(FAILURE_WINDOW_SECONDS)},
    )


def failed_credential(db, account_hash, origin_hash, state, action):
    timestamp, account_count, origin_count = state
    record_failure(db, account_hash, origin_hash, timestamp)
    details = {'account_hash': account_hash, 'origin_hash': origin_hash}
    audit(db, None, action, 'authentication', details=details)
    # Emit the block event at the threshold, not on every blocked request.
    if limited((timestamp, account_count + 1, origin_count + 1)):
        audit(db, None, 'CREDENCIAL_BLOQUEADA', 'authentication', details=details)


@app.post('/api/auth/password')
def change_own_password(data: dict, request: Request, user=Depends(current_user)):
    if set(data) != {'current_password', 'new_password'}:
        fail('Informe a senha atual e a nova senha.')
    current = text(data['current_password'], 'Senha atual', maximum=128)
    replacement = password(data['new_password'])
    with connect(write=True) as db:
        # Recheck the session while holding the writer lock: a concurrently
        # revoked cookie cannot change credentials after its revocation.
        token_hash = hashlib.sha256(request.cookies.get('compac_session', '').encode()).hexdigest()
        row = db.execute(
            'SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id '
            'WHERE u.id=? AND s.token_hash=? AND s.expires_at>? AND u.active=1',
            (user['id'], token_hash, now()),
        ).fetchone()
        if not row:
            fail('Entre na sua conta para continuar.', 401)
        account_hash, origin_hash = credential_keys(row['username'], request)
        state = failure_state(db, account_hash, origin_hash)
        if limited(state):
            return credential_limit_response()
        if not verify_password(current, row['password_hash']):
            failed_credential(db, account_hash, origin_hash, state, 'TROCA_SENHA_FALHOU')
            return JSONResponse({'detail': 'Senha atual inválida.'}, status_code=403)
        if hmac.compare_digest(current.encode(), replacement.encode()):
            fail('Escolha uma senha diferente da atual.')
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (hash_password(replacement), row['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
        audit(db, row['id'], 'TROCAR_SENHA', 'users', row['id'])
        response = JSONResponse({'ok': True, 'reauthenticate': True})
        response.delete_cookie('compac_session')
        return response


@app.post('/api/auth/logout')
def logout(request: Request):
    with connect(write=True) as db:
        db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(request.cookies.get('compac_session', '').encode()).hexdigest(),))
    response = JSONResponse({'ok': True})
    response.delete_cookie('compac_session')
    return response


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return user


@app.get('/api/users')
def users(user=Depends(current_user)):
    with connect() as db:
        return [public_user(row) for row in db.execute('SELECT * FROM users ORDER BY name')]


@app.post('/api/users', status_code=201)
def add_user(data: dict, user=Depends(administrator)):
    username = text(data.get('username'), 'Usuário', maximum=80)
    name = text(data.get('name'), 'Nome', maximum=120)
    role = data.get('role')
    if role not in ROLES:
        fail('Perfil inválido.')
    hashed = hash_password(password(data.get('password')))
    with connect(write=True) as db:
        key = db.execute('INSERT INTO users(username,name,password_hash,role,created_at) VALUES(?,?,?,?,?) RETURNING id', (username, name, hashed, role, now())).fetchone()['id']
        audit(db, user['id'], 'CRIAR', 'users', key, {'username': username, 'role': role})
        return public_user(reference(db, 'users', key))


@app.patch('/api/users/{key}')
def edit_user(key: int, data: dict, user=Depends(administrator)):
    with connect(write=True) as db:
        row = reference(db, 'users', key)
        role, active = data.get('role', row['role']), data.get('active', bool(row['active']))
        if role not in ROLES or not isinstance(active, bool):
            fail('Perfil ou situação inválidos.')
        if key == user['id'] and (role != 'ADMIN' or not active):
            fail('Você não pode remover seu próprio acesso de administrador.')
        db.execute('UPDATE users SET role=?,active=? WHERE id=?', (role, int(active), key))
        if 'password' in data:
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (hash_password(password(data['password'])), key))
        if 'password' in data or not active or role != row['role']:
            db.execute('DELETE FROM sessions WHERE user_id=?', (key,))
        audit(db, user['id'], 'ATUALIZAR', 'users', key, {'role': role, 'active': active, 'password_changed': 'password' in data})
        return public_user(reference(db, 'users', key))


@app.get('/api/schema')
def schema(user=Depends(current_user)):
    return ENTITIES


def validate_entity(db, entity, data):
    fields = ENTITIES[entity]['fields']
    if set(data) - set(fields):
        fail('O formulário contém campos desconhecidos.')
    result = {}
    for key, spec in fields.items():
        value, kind = data.get(key), spec['kind']
        if value in ('', None) and not spec['required']:
            result[key] = 0 if kind == 'boolean' else None
        elif kind == 'relation':
            result[key] = reference(db, spec['relation'], value)['id']
        elif kind == 'number':
            result[key] = float(number(value, spec['label'], spec.get('minimum', 0), 2 if key == 'unit_cost' else 3))
        elif kind == 'boolean':
            if not isinstance(value, bool):
                fail(f"{spec['label']}: valor inválido.")
            result[key] = int(value)
        elif kind == 'select':
            if value not in spec['options']:
                fail(f"{spec['label']}: opção inválida.")
            result[key] = value
        elif kind == 'date':
            try:
                result[key] = date.fromisoformat(value).isoformat()
            except (TypeError, ValueError):
                fail(f"{spec['label']}: data inválida.")
        else:
            result[key] = text(value, spec['label'], spec['required'], 2000 if kind == 'textarea' else 500)
    if entity == 'expenses':
        result['total_cost'] = float((Decimal(str(result['quantity'])) * Decimal(str(result['unit_cost']))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    if entity == 'equipment' and not reference(db, 'materials', result['material_id'])['individualizable']:
        fail('Marque o material como patrimônio antes de cadastrar a unidade.')
    return result


@app.get('/api/catalog/{entity}')
def list_entity(entity: str, user=Depends(current_user)):
    if entity not in ENTITIES:
        fail('Cadastro não encontrado.', 404)
    with connect() as db:
        return [dict(row) for row in db.execute(f'SELECT * FROM {entity} ORDER BY id DESC')]


@app.post('/api/catalog/{entity}', status_code=201)
def create_entity(entity: str, data: dict, user=Depends(operator)):
    if entity not in ENTITIES:
        fail('Cadastro não encontrado.', 404)
    with connect(write=True) as db:
        values = validate_entity(db, entity, data)
        key = db.execute(f"INSERT INTO {entity}({','.join(values)}) VALUES({','.join('?' for _ in values)}) RETURNING id", tuple(values.values())).fetchone()['id']
        audit(db, user['id'], 'CRIAR', entity, key, values)
        return dict(reference(db, entity, key))


@app.put('/api/catalog/{entity}/{key}')
def update_entity(entity: str, key: int, data: dict, user=Depends(operator)):
    if entity not in ENTITIES:
        fail('Cadastro não encontrado.', 404)
    with connect(write=True) as db:
        previous = dict(reference(db, entity, key))
        values = validate_entity(db, entity, data)
        if entity == 'materials' and any(values[field] != previous[field] for field in ('unit', 'individualizable')):
            # Historical amounts and asset identity use this material's unit
            # and mode. Even zero balances/closed loans retain that meaning.
            history_tables = ('balances', 'movements', 'loans', 'equipment', 'requisition_items', 'expenses', 'consumption_profiles')
            if any(db.execute(f'SELECT 1 FROM {table} WHERE material_id=? LIMIT 1', (key,)).fetchone() for table in history_tables):
                fail('Unidade e controle patrimonial não podem ser alterados após vínculos de estoque, patrimônio ou histórico operacional.', 409)
        if entity == 'equipment' and values['status'] != 'MANUTENCAO' and db.execute("SELECT 1 FROM maintenance WHERE equipment_id=? AND status='ABERTA'", (key,)).fetchone():
            fail('Conclua a manutenção antes de liberar o patrimônio.')
        db.execute(f"UPDATE {entity} SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), key))
        audit(db, user['id'], 'ATUALIZAR', entity, key, {'before': previous, 'after': values})
        return dict(reference(db, entity, key))


def scaled(row):
    result = dict(row)
    result['quantity'] /= 1000
    return result


def balance_delta(db, material, location, delta):
    db.execute('INSERT INTO balances(material_id,location_id,quantity) VALUES(?,?,0) ON CONFLICT(material_id,location_id) DO NOTHING', (material, location))
    old = db.execute('SELECT quantity FROM balances WHERE material_id=? AND location_id=?', (material, location)).fetchone()['quantity']
    if old + delta < 0:
        fail('Saldo insuficiente na localização de origem.', 409)
    db.execute('UPDATE balances SET quantity=quantity+? WHERE material_id=? AND location_id=?', (delta, material, location))


def perform_movement(db, data, user, requisition=None):
    kind = data.get('type')
    if kind not in ('ENTRADA', 'SAIDA', 'DEVOLUCAO', 'TRANSFERENCIA', 'AJUSTE'):
        fail('Tipo de movimentação inválido.')
    if kind == 'AJUSTE' and user['role'] != 'ADMIN':
        fail('Somente administradores podem ajustar o saldo.', 403)
    material = (reference if kind in ('DEVOLUCAO', 'AJUSTE') else active_reference)(db, 'materials', data.get('material_id'))['id']
    amount = quantity(data.get('quantity'), 0 if kind == 'AJUSTE' else 0.001)
    origin = destination = employee = None
    if kind in ('SAIDA', 'TRANSFERENCIA'):
        origin = reference(db, 'locations', data.get('origin_id'))['id']
    if kind in ('ENTRADA', 'DEVOLUCAO', 'TRANSFERENCIA', 'AJUSTE'):
        destination = reference(db, 'locations', data.get('destination_id'))['id']
    if kind == 'TRANSFERENCIA' and origin == destination:
        fail('Origem e destino devem ser diferentes.')
    if data.get('employee_id') not in (None, ''):
        employee = (reference if kind == 'DEVOLUCAO' else active_reference)(db, 'employees', data['employee_id'])['id']
    notes = text(data.get('notes', ''), 'Justificativa', kind == 'AJUSTE') or ''
    due_date = None
    if kind == 'SAIDA' and employee and data.get('due_date'):
        try:
            due_date = date.fromisoformat(data['due_date']).isoformat()
        except (ValueError, TypeError):
            fail('Prazo de devolução inválido.')
    if kind == 'DEVOLUCAO':
        if not employee:
            fail('Informe o funcionário responsável pela devolução.')
        loans = db.execute('SELECT * FROM loans WHERE employee_id=? AND material_id=? AND quantity>0 ORDER BY id', (employee, material)).fetchall()
        if sum(row['quantity'] for row in loans) < amount:
            fail('Devolução maior que a pendência do funcionário.', 409)
        remaining = amount
        for loan in loans:
            returned = min(remaining, loan['quantity'])
            db.execute('UPDATE loans SET quantity=quantity-? WHERE id=?', (returned, loan['id']))
            remaining -= returned
            if not remaining:
                break
    if origin:
        balance_delta(db, material, origin, -amount)
    delta = amount
    if destination:
        if kind == 'AJUSTE':
            old = db.execute('SELECT quantity FROM balances WHERE material_id=? AND location_id=?', (material, destination)).fetchone()
            delta -= old['quantity'] if old else 0
        balance_delta(db, material, destination, delta)
    recorded = delta if kind == 'AJUSTE' else amount
    key = db.execute('INSERT INTO movements(type,material_id,quantity,origin_id,destination_id,employee_id,notes,user_id,created_at,requisition_id) VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id',
                     (kind, material, recorded, origin, destination, employee, notes, user['id'], now(), requisition)).fetchone()['id']
    if kind == 'SAIDA' and employee:
        db.execute('INSERT INTO loans(employee_id,material_id,location_id,quantity,due_date,movement_id,created_at) VALUES(?,?,?,?,?,?,?)', (employee, material, origin, amount, due_date, key, now()))
    audit(db, user['id'], kind, 'movements', key, {'material_id': material, 'quantity': recorded / 1000, 'origin_id': origin, 'destination_id': destination, 'notes': notes})
    return key


@app.post('/api/movements', status_code=201)
def add_movement(data: dict, request: Request, user=Depends(operator)):
    from .idempotency import replay_or_execute, validate_key

    key = validate_key(request.headers.get('Idempotency-Key'))
    with connect(write=True) as db:
        return replay_or_execute(
            db, user['id'], 'POST /api/movements', key, data,
            lambda: {'id': perform_movement(db, data, user)},
        )


@app.get('/api/movements')
def movements(user=Depends(current_user)):
    with connect() as db:
        return [scaled(row) for row in db.execute('SELECT m.*,mat.description material,mat.unit,o.name origin,d.name destination,e.name employee,u.name author FROM movements m JOIN materials mat ON mat.id=m.material_id LEFT JOIN locations o ON o.id=m.origin_id LEFT JOIN locations d ON d.id=m.destination_id LEFT JOIN employees e ON e.id=m.employee_id JOIN users u ON u.id=m.user_id ORDER BY m.id DESC')]


def stock_rows(db):
    return [dict(row) for row in db.execute('SELECT m.id material_id,m.code,m.description material,m.unit,m.minimum_stock,b.location_id,l.name location,l.work_id,COALESCE(b.quantity,0)/1000.0 quantity FROM materials m LEFT JOIN balances b ON b.material_id=m.id LEFT JOIN locations l ON l.id=b.location_id ORDER BY m.description,l.name')]


@app.get('/api/stock')
def stock(user=Depends(current_user)):
    with connect() as db:
        return stock_rows(db)


@app.get('/api/loans')
def loans(user=Depends(current_user)):
    with connect() as db:
        return [scaled(row) for row in db.execute("SELECT p.*,e.name employee,m.description material,m.unit,l.name location FROM loans p JOIN employees e ON e.id=p.employee_id JOIN materials m ON m.id=p.material_id JOIN locations l ON l.id=p.location_id WHERE p.quantity>0 ORDER BY COALESCE(p.due_date,'9999'),p.id")]


@app.get('/api/requisitions')
def requisitions(user=Depends(current_user)):
    with connect() as db:
        rows = [dict(r) for r in db.execute('SELECT r.*,w.name work,u.name requester FROM requisitions r JOIN works w ON w.id=r.work_id JOIN users u ON u.id=r.requester_id ORDER BY r.id DESC')]
        for row in rows:
            row['items'] = [scaled(r) for r in db.execute('SELECT i.*,m.description material,m.unit FROM requisition_items i JOIN materials m ON m.id=i.material_id WHERE i.requisition_id=?', (row['id'],))]
        return rows


@app.post('/api/requisitions', status_code=201)
def add_requisition(data: dict, user=Depends(operator)):
    with connect(write=True) as db:
        work = active_reference(db, 'works', data.get('work_id'))['id']
        priority = data.get('priority')
        if priority not in PRIORITIES:
            fail('Prioridade inválida.')
        items = data.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 100 or any(not isinstance(i, dict) for i in items):
            fail('Inclua entre 1 e 100 materiais.')
        validated = []
        for item in items:
            material = active_reference(db, 'materials', item.get('material_id'))['id']
            if material in [i[0] for i in validated]:
                fail('Agrupe o mesmo material em um único item.')
            validated.append((material, quantity(item.get('quantity'))))
        key = db.execute('INSERT INTO requisitions(work_id,requester_id,priority,notes,created_at) VALUES(?,?,?,?,?) RETURNING id', (work, user['id'], priority, text(data.get('notes', ''), 'Observações', False) or '', now())).fetchone()['id']
        db.executemany('INSERT INTO requisition_items(requisition_id,material_id,quantity) VALUES(?,?,?)', [(key, *item) for item in validated])
        audit(db, user['id'], 'CRIAR', 'requisitions', key)
        return {'id': key}


@app.post('/api/requisitions/{key}/action')
def requisition_action(key: int, data: dict, user=Depends(operator)):
    with connect(write=True) as db:
        row = reference(db, 'requisitions', key)
        action = data.get('action')
        if action == 'CANCELAR':
            if row['status'] not in ('PENDENTE', 'APROVADA'):
                fail('Esta requisição não pode ser cancelada.', 409)
            status = 'CANCELADA'
        elif action == 'APROVAR':
            if user['role'] != 'ADMIN':
                fail('A aprovação exige um administrador.', 403)
            if row['status'] != 'PENDENTE':
                fail('A requisição não está pendente.', 409)
            status = 'APROVADA'
        elif action == 'ATENDER':
            if row['status'] != 'APROVADA':
                fail('A requisição não está aprovada.', 409)
            origin = reference(db, 'locations', data.get('origin_id'))['id']
            destination = reference(db, 'locations', data.get('destination_id'))
            if destination['work_id'] != row['work_id']:
                fail('O destino deve pertencer à obra da requisição.')
            for item in db.execute('SELECT * FROM requisition_items WHERE requisition_id=?', (key,)).fetchall():
                perform_movement(db, {'type': 'TRANSFERENCIA', 'material_id': item['material_id'], 'quantity': item['quantity'] / 1000, 'origin_id': origin, 'destination_id': destination['id'], 'notes': f'Requisição #{key}'}, user, key)
            status = 'ATENDIDA'
        else:
            fail('Ação inválida.')
        db.execute('UPDATE requisitions SET status=? WHERE id=?', (status, key))
        audit(db, user['id'], action, 'requisitions', key)
        return {'status': status}


@app.get('/api/tickets')
def tickets(user=Depends(current_user)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT t.*,w.name work,u.name assignee,c.name creator FROM tickets t LEFT JOIN works w ON w.id=t.work_id LEFT JOIN users u ON u.id=t.assignee_id JOIN users c ON c.id=t.creator_id ORDER BY t.id DESC')]


def assignee_reference(db, value):
    row = reference(db, 'users', value, True)
    if row and (not row['active'] or row['role'] == 'CONSULTA'):
        fail('Selecione um responsável ativo com permissão de operação.')
    return row['id'] if row else None


@app.post('/api/tickets', status_code=201)
def add_ticket(data: dict, user=Depends(operator)):
    title = text(data.get('title'), 'Título', maximum=160)
    description = text(data.get('description'), 'Descrição', maximum=5000)
    if data.get('priority') not in PRIORITIES:
        fail('Prioridade inválida.')
    with connect(write=True) as db:
        work = reference(db, 'works', data.get('work_id'), True)
        assignee = assignee_reference(db, data.get('assignee_id'))
        key = db.execute('INSERT INTO tickets(title,description,priority,work_id,assignee_id,creator_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id', (title, description, data['priority'], work['id'] if work else None, assignee, user['id'], now(), now())).fetchone()['id']
        audit(db, user['id'], 'ABRIR', 'tickets', key)
        return {'id': key}


@app.get('/api/tickets/{key}')
def ticket_detail(key: int, user=Depends(current_user)):
    with connect() as db:
        row = dict(reference(db, 'tickets', key))
        row['comments'] = [dict(r) for r in db.execute('SELECT c.*,u.name author FROM ticket_comments c JOIN users u ON u.id=c.user_id WHERE c.ticket_id=? ORDER BY c.id', (key,))]
        row['history'] = [dict(r) for r in db.execute("SELECT a.*,u.name author FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE entity='tickets' AND record_id=? ORDER BY a.id", (key,))]
        return row


@app.post('/api/tickets/{key}/comments', status_code=201)
def add_comment(key: int, data: dict, user=Depends(operator)):
    body = text(data.get('body'), 'Comentário', maximum=5000)
    with connect(write=True) as db:
        reference(db, 'tickets', key)
        cid = db.execute('INSERT INTO ticket_comments(ticket_id,user_id,body,created_at) VALUES(?,?,?,?) RETURNING id', (key, user['id'], body, now())).fetchone()['id']
        db.execute('UPDATE tickets SET updated_at=? WHERE id=?', (now(), key))
        audit(db, user['id'], 'COMENTAR', 'tickets', key)
        return {'id': cid}


@app.patch('/api/tickets/{key}')
def edit_ticket(key: int, data: dict, user=Depends(operator)):
    with connect(write=True) as db:
        row = reference(db, 'tickets', key)
        transitions = {'ABERTO': ['EM_ANDAMENTO', 'CANCELADO'], 'EM_ANDAMENTO': ['RESOLVIDO', 'CANCELADO'], 'RESOLVIDO': ['ABERTO'], 'CANCELADO': ['ABERTO']}
        status = data.get('status', row['status'])
        if status != row['status'] and status not in transitions[row['status']]:
            fail('Transição de chamado inválida.', 409)
        priority = data.get('priority', row['priority'])
        if priority not in PRIORITIES:
            fail('Prioridade inválida.')
        assignee = assignee_reference(db, data.get('assignee_id', row['assignee_id']))
        db.execute('UPDATE tickets SET status=?,priority=?,assignee_id=?,updated_at=? WHERE id=?', (status, priority, assignee, now(), key))
        audit(db, user['id'], 'ATUALIZAR', 'tickets', key, {'before': {'status': row['status'], 'priority': row['priority'], 'assignee_id': row['assignee_id']}, 'after': {'status': status, 'priority': priority, 'assignee_id': assignee}})
        return {'status': status}


@app.get('/api/maintenance')
def maintenance(user=Depends(current_user)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT m.*,e.asset_tag,mat.description material FROM maintenance m JOIN equipment e ON e.id=m.equipment_id JOIN materials mat ON mat.id=e.material_id ORDER BY m.id DESC')]


@app.post('/api/maintenance', status_code=201)
def open_maintenance(data: dict, user=Depends(operator)):
    with connect(write=True) as db:
        equipment = reference(db, 'equipment', data.get('equipment_id'))
        if equipment['status'] in ('BAIXADO', 'MANUTENCAO'):
            fail('O patrimônio não está disponível para abrir manutenção.', 409)
        defect = text(data.get('defect'), 'Defeito')
        key = db.execute('INSERT INTO maintenance(equipment_id,defect,created_at,user_id) VALUES(?,?,?,?) RETURNING id', (equipment['id'], defect, now(), user['id'])).fetchone()['id']
        db.execute("UPDATE equipment SET status='MANUTENCAO' WHERE id=?", (equipment['id'],))
        audit(db, user['id'], 'ABRIR', 'maintenance', key)
        return {'id': key}


@app.post('/api/maintenance/{key}/close')
def close_maintenance(key: int, data: dict, user=Depends(operator)):
    with connect(write=True) as db:
        row = reference(db, 'maintenance', key)
        if row['status'] != 'ABERTA':
            fail('Esta manutenção já foi concluída.', 409)
        resolution = text(data.get('resolution'), 'Solução')
        condition = data.get('condition')
        if condition not in ('BOA', 'REGULAR', 'RUIM'):
            fail('Condição inválida.')
        db.execute("UPDATE maintenance SET status='CONCLUIDA',resolution=?,closed_at=? WHERE id=?", (resolution, now(), key))
        db.execute("UPDATE equipment SET status='DISPONIVEL',condition=? WHERE id=?", (condition, row['equipment_id']))
        audit(db, user['id'], 'CONCLUIR', 'maintenance', key, {'resolution': resolution})
        return {'ok': True}


def alert_rows(db):
    result = []
    for r in db.execute("SELECT m.id,m.description,m.minimum_stock,COALESCE(SUM(b.quantity),0)/1000.0 quantity FROM materials m LEFT JOIN balances b ON b.material_id=m.id WHERE m.status='ATIVO' GROUP BY m.id HAVING COALESCE(SUM(b.quantity),0)/1000.0<m.minimum_stock"):
        result.append({'type': 'ESTOQUE', 'priority': 'ALTA', 'message': f"{r['description']}: saldo {r['quantity']:g}, mínimo {r['minimum_stock']:g}.", 'module': 'stock'})
    today = datetime.now(ZoneInfo(os.getenv('COMPAC_TIMEZONE', 'America/Sao_Paulo'))).date().isoformat()
    for r in db.execute('SELECT e.name,m.description,l.due_date FROM loans l JOIN employees e ON e.id=l.employee_id JOIN materials m ON m.id=l.material_id WHERE l.quantity>0 AND l.due_date<?', (today,)):
        result.append({'type': 'DEVOLUCAO', 'priority': 'ALTA', 'message': f"{r['name']} • {r['description']} com devolução vencida em {r['due_date']}.", 'module': 'loans'})
    for r in db.execute("SELECT id,title FROM tickets WHERE priority='URGENTE' AND status IN ('ABERTO','EM_ANDAMENTO')"):
        result.append({'type': 'CHAMADO', 'priority': 'URGENTE', 'message': f"Chamado #{r['id']}: {r['title']}", 'module': 'tickets'})
    return result


@app.get('/api/alerts')
def alerts(user=Depends(current_user)):
    with connect() as db:
        return alert_rows(db)


@app.get('/api/dashboard')
def dashboard(user=Depends(current_user)):
    with connect() as db:
        count = lambda sql: db.execute(sql).fetchone()[0]
        return {'materials': count("SELECT COUNT(*) FROM materials WHERE status='ATIVO'"),
                'open_tickets': count("SELECT COUNT(*) FROM tickets WHERE status IN ('ABERTO','EM_ANDAMENTO')"),
                'pending_requisitions': count("SELECT COUNT(*) FROM requisitions WHERE status IN ('PENDENTE','APROVADA')"),
                'open_loans': count('SELECT COUNT(*) FROM loans WHERE quantity>0'),
                'expenses': count('SELECT ROUND(COALESCE(SUM(total_cost),0),2) FROM expenses'),
                'alerts': alert_rows(db),
                'recent': [dict(r) for r in db.execute('SELECT m.id,m.type,m.quantity/1000.0 quantity,mat.description material,mat.unit,m.created_at,u.name author FROM movements m JOIN materials mat ON mat.id=m.material_id JOIN users u ON u.id=m.user_id ORDER BY m.id DESC LIMIT 6')],
                'expense_by_work': [dict(r) for r in db.execute("SELECT COALESCE(w.name,'Sem obra') name,ROUND(SUM(e.total_cost),2) total FROM expenses e LEFT JOIN works w ON w.id=e.work_id GROUP BY e.work_id,w.name ORDER BY total DESC")]}


@app.get('/api/forecast')
def forecast(work_id: int, activity: str, quantity_produced: float, user=Depends(current_user)):
    produced = number(quantity_produced, minimum=0.001)
    with connect() as db:
        reference(db, 'works', work_id)
        rows = [dict(r) for r in db.execute('SELECT p.material_id,SUM(p.consumption_per_unit) consumption_per_unit,m.description material,m.unit,COALESCE((SELECT SUM(b.quantity)/1000.0 FROM balances b JOIN locations l ON l.id=b.location_id WHERE b.material_id=p.material_id AND l.work_id=p.work_id),0) available FROM consumption_profiles p JOIN materials m ON m.id=p.material_id WHERE p.work_id=? AND LOWER(p.activity)=LOWER(?) GROUP BY p.material_id,p.work_id,m.description,m.unit', (work_id, activity))]
        for r in rows:
            r['expected'] = float((Decimal(str(r['consumption_per_unit'])) * produced).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP))
            r['shortage'] = max(0, round(r['expected'] - r['available'], 3))
        return rows


@app.get('/api/audit')
def history(user=Depends(administrator)):
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT a.*,u.name author FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 2000')]


EXPORTS = {
 'movements': 'SELECT m.id Registro,m.type Tipo,mat.code Codigo,mat.description Material,mat.unit Unidade,m.quantity/1000.0 Quantidade,o.name Origem,d.name Destino,e.name Funcionario,u.name Usuario,m.notes Observacoes,m.created_at Data FROM movements m JOIN materials mat ON mat.id=m.material_id LEFT JOIN locations o ON o.id=m.origin_id LEFT JOIN locations d ON d.id=m.destination_id LEFT JOIN employees e ON e.id=m.employee_id JOIN users u ON u.id=m.user_id ORDER BY m.id',
 'expenses': 'SELECT e.id Registro,e.supplier Fornecedor,e.document_number Documento,e.purchase_date Data,m.description Material,m.unit Unidade,w.name Obra,e.quantity Quantidade,e.unit_cost Custo_unitario,e.total_cost Total FROM expenses e JOIN materials m ON m.id=e.material_id LEFT JOIN works w ON w.id=e.work_id ORDER BY e.id',
 'requisitions': 'SELECT r.id Requisicao,w.name Obra,u.name Solicitante,r.priority Prioridade,r.status Situacao,r.created_at Data,m.description Material,m.unit Unidade,i.quantity/1000.0 Quantidade,r.notes Observacoes FROM requisitions r JOIN works w ON w.id=r.work_id JOIN users u ON u.id=r.requester_id JOIN requisition_items i ON i.requisition_id=r.id JOIN materials m ON m.id=i.material_id ORDER BY r.id,i.id',
 'tickets': 'SELECT t.id Chamado,t.title Titulo,t.description Descricao,t.priority Prioridade,t.status Situacao,w.name Obra,u.name Responsavel,c.name Solicitante,t.created_at Abertura,t.updated_at Atualizacao FROM tickets t LEFT JOIN works w ON w.id=t.work_id LEFT JOIN users u ON u.id=t.assignee_id JOIN users c ON c.id=t.creator_id ORDER BY t.id',
 'production': 'SELECT p.id Registro,w.name Obra,p.activity Atividade,p.quantity_produced Quantidade,p.produced_at Data FROM production p JOIN works w ON w.id=p.work_id ORDER BY p.id',
}


@app.get('/api/export/{entity}')
def export(entity: str, user=Depends(current_user)):
    with connect() as db:
        if entity == 'stock':
            rows = stock_rows(db)
        elif entity in EXPORTS:
            rows = [dict(r) for r in db.execute(EXPORTS[entity])]
        else:
            fail('Relatório não encontrado.', 404)
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=';')
    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in row.values()])
    else:
        writer.writerow(['Sem registros'])
    return Response('\ufeff' + stream.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="compac-{entity}.csv"'})


from .attendance.routes import register_attendance
register_attendance(app, administrator)

from .attendance.device import register_device_routes
register_device_routes(app, administrator)

from .attendance.face import register_face_routes
register_face_routes(app, administrator)


@app.get('/ponto-facial', include_in_schema=False)
def attendance_terminal_page():
    return FileResponse(STATIC / 'attendance-terminal.html', headers={'Cache-Control': 'no-store'})


@app.get('/ponto-facial/configuracao', include_in_schema=False)
def attendance_terminal_configuration(user=Depends(administrator)):
    return FileResponse(STATIC / 'attendance-admin.html', headers={'Cache-Control': 'no-store'})
