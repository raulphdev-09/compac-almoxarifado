"""Reviewed, atomic CSV/XLSX imports for the legacy COMPAC inventory.

Application services are injected so this module never imports ``app.main``.
Preview deliberately executes the same services inside rolled back savepoints;
no separate approximation of stock, loan, or catalog rules can become stale.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import psycopg
from fastapi import Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from .idempotency import replay_or_execute, validate_key


MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
MAX_JSON_BYTES = ((MAX_BYTES + 2) // 3) * 4 + 4096
PREVIEW_SECONDS = 15 * 60
_LOCAL_SECRET = secrets.token_bytes(32)
_SOURCE_TYPES = ('INVENTARIO_INICIAL', 'NOTA_FISCAL', 'OUTRO_RECEBIMENTO')
_COLUMNS = {
    'materials': (
        'codigo', 'descricao', 'categoria', 'unidade', 'minimo',
        'saldo_inicial', 'local', 'tipo_origem', 'referencia',
    ),
    'movements': (
        'tipo', 'codigo_material', 'quantidade', 'origem', 'destino',
        'matricula', 'finalidade', 'tipo_origem', 'referencia', 'observacoes',
    ),
}
_REQUIRED = {
    'materials': {'codigo', 'descricao', 'categoria', 'unidade'},
    'movements': {'tipo', 'codigo_material', 'quantidade'},
}
_ALIASES = {
    'materials': {
        'code': 'codigo', 'description': 'descricao', 'category': 'categoria',
        'unit': 'unidade', 'minimum_stock': 'minimo', 'estoque_minimo': 'minimo',
        'estoque_inicial': 'saldo_inicial', 'localizacao': 'local',
        'origem_estoque': 'tipo_origem', 'source_type': 'tipo_origem',
        'source_reference': 'referencia',
    },
    'movements': {
        'codigo': 'codigo_material', 'material_codigo': 'codigo_material',
        'type': 'tipo', 'quantity': 'quantidade', 'matricula_funcionario': 'matricula',
        'purpose': 'finalidade', 'source_type': 'tipo_origem',
        'source_reference': 'referencia', 'notes': 'observacoes',
    },
}


class ImportRow(dict):
    """Keep a source line without exposing an extra importable data column."""

    def __init__(self, values, source_row):
        super().__init__(values)
        self.source_row = source_row


def _reject(message, status=422):
    raise HTTPException(status, message)


def _entity(entity):
    if entity not in _COLUMNS:
        _reject('Importação disponível somente para materiais e movimentações.', 404)


def _header(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    return re.sub(r'[\s-]+', '_', value.strip().lower())


async def _json_body(request):
    """Bound chunked requests as well as requests with Content-Length."""
    parts, total = [], 0
    async for part in request.stream():
        total += len(part)
        if total > MAX_JSON_BYTES:
            _reject('Arquivo excede o limite de 2 MiB.', 413)
        parts.append(part)
    try:
        result = json.loads(b''.join(parts))
    except (ValueError, UnicodeError, RecursionError):
        _reject('Envie um objeto JSON válido com o arquivo em base64.')
    if not isinstance(result, dict):
        _reject('Envie um objeto JSON válido com o arquivo em base64.')
    return result


def _upload(data, *, confirming=False):
    allowed = {'filename', 'content_base64'} | ({'preview_token'} if confirming else set())
    if set(data) != allowed:
        _reject('Informe somente nome do arquivo, conteúdo base64 e, na confirmação, o token da prévia.')
    filename = data.get('filename')
    if (not isinstance(filename, str) or not filename or len(filename) > 180
            or any(ord(c) < 32 for c in filename) or '/' in filename or '\\' in filename
            or not filename.lower().endswith(('.csv', '.xlsx'))):
        _reject('Informe um nome de arquivo CSV ou XLSX válido, sem caminho de pastas.')
    encoded = data.get('content_base64')
    if not isinstance(encoded, str):
        _reject('Conteúdo do arquivo inválido. Envie base64.')
    if len(encoded) > ((MAX_BYTES + 2) // 3) * 4:
        _reject('Arquivo excede o limite de 2 MiB.', 413)
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        _reject('Conteúdo do arquivo inválido. Envie base64.')
    if not content:
        _reject('O arquivo está vazio.')
    if len(content) > MAX_BYTES:
        _reject('Arquivo excede o limite de 2 MiB.', 413)
    return filename, content, hashlib.sha256(content).hexdigest()


def _table(entity, content, filename):
    from .document_formats import parse_table

    try:
        headers, rows = parse_table(content, filename, max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
    except ValueError as exc:
        _reject(str(exc))
    names = [_ALIASES[entity].get(_header(name), _header(name)) for name in headers]
    if len(set(names)) != len(names):
        _reject('Cabeçalhos duplicados: cada coluna deve aparecer uma única vez.')
    unknown = set(names) - set(_COLUMNS[entity])
    if unknown:
        _reject('Colunas não permitidas: ' + ', '.join(sorted(unknown)) + '. Use o modelo de importação; datas e saldos prontos não são importáveis.')
    missing = _REQUIRED[entity] - set(names)
    if missing:
        _reject('Colunas obrigatórias ausentes: ' + ', '.join(sorted(missing)) + '.')
    if not rows:
        _reject('O arquivo não contém linhas de dados.')
    return [ImportRow(
        {name: row.get(original, '').strip() for original, name in zip(headers, names)},
        getattr(row, 'source_row', index),
    ) for index, row in enumerate(rows, 2)]


def _secret():
    setup = os.getenv('COMPAC_SETUP_TOKEN', '')
    if setup:
        return hmac.new(setup.encode(), b'COMPAC/import-preview/v1', hashlib.sha256).digest()
    if os.getenv('RENDER') == 'true' or os.getenv('COMPAC_REQUIRE_POSTGRES') == '1':
        _reject('Chave de importação indisponível. Solicite a configuração ao administrador.', 503)
    return _LOCAL_SECRET


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _issue_token(actor_id, entity, digest, filename):
    issued = int(time.time())
    claims = {
        'v': 1, 'actor': actor_id, 'entity': entity, 'sha256': digest,
        'filename': filename, 'nonce': secrets.token_hex(16),
        'issued': issued, 'expires': issued + PREVIEW_SECONDS,
    }
    encoded = _b64(json.dumps(claims, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())
    signature = _b64(hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest())
    return encoded + '.' + signature, claims


def _verify_token(token, actor_id, entity, digest, filename):
    if not isinstance(token, str) or len(token) > 2048:
        _reject('Prévia inválida. Gere uma nova prévia antes de confirmar.', 409)
    secret = _secret()
    try:
        encoded, signature = token.split('.')
        expected = _b64(hmac.new(secret, encoded.encode('ascii'), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        claims = json.loads(base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True))
        if (set(claims) != {'v', 'actor', 'entity', 'sha256', 'filename', 'nonce', 'issued', 'expires'}
                or claims['v'] != 1 or claims['actor'] != actor_id or claims['entity'] != entity
                or claims['sha256'] != digest or claims['filename'] != filename
                or not isinstance(claims['nonce'], str) or re.fullmatch('[0-9a-f]{32}', claims['nonce']) is None
                or type(claims['issued']) is not int or type(claims['expires']) is not int
                or claims['expires'] != claims['issued'] + PREVIEW_SECONDS):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error):
        _reject('Prévia inválida ou arquivo alterado. Gere uma nova prévia.', 409)
    current = int(time.time())
    if claims['issued'] > current + 30 or claims['expires'] <= current:
        _reject('A prévia expirou. Gere uma nova prévia antes de confirmar.', 409)
    return claims


def _text(row, column, *, required=True, maximum=500):
    value = row.get(column, '').strip()
    if (required and not value) or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        _reject(f'{column}: informe um texto válido com até {maximum} caracteres.')
    return value


def _amount(row, column, *, positive=False, default=None):
    raw = row.get(column, '')
    if not raw and default is not None:
        return Decimal(str(default))
    if re.fullmatch(r'\d+(?:[.,]\d{1,3})?', raw or '') is None:
        _reject(f'{column}: use um número sem separador de milhar, com até 3 casas decimais e sem sinal negativo.')
    try:
        value = Decimal(raw.replace(',', '.'))
    except InvalidOperation:
        _reject(f'{column}: informe uma quantidade válida.')
    if value > 1000000000 or (value <= 0 if positive else value < 0):
        _reject(f'{column}: informe uma quantidade {"maior que zero" if positive else "a partir de zero"}, até 1000000000.')
    return value


def _lookup(db, table, column, value, label):
    # Identifiers are exclusively module constants; uploaded values are bound.
    found = db.execute(f'SELECT * FROM {table} WHERE LOWER({column})=LOWER(?)', (value,)).fetchall()
    if len(found) != 1:
        _reject(f'{label}: registro não encontrado ou nome ambíguo. Cadastre ou corrija o vínculo antes de importar.')
    return found[0]


def _source(row):
    source_type = _text(row, 'tipo_origem', maximum=100).upper()
    if source_type not in _SOURCE_TYPES:
        _reject('tipo_origem: use INVENTARIO_INICIAL, NOTA_FISCAL ou OUTRO_RECEBIMENTO.')
    reference = _text(row, 'referencia', required=source_type != 'INVENTARIO_INICIAL', maximum=200)
    return {'source_type': source_type, 'source_reference': reference}


def _notes(row, filename, batch_id, line):
    notes = _text(row, 'observacoes', required=False, maximum=1200)
    return f'Importação {batch_id}; arquivo {filename}; linha {line}.' + (f' {notes}' if notes else '')


def _material(db, row, user, callbacks, filename, batch_id, line):
    code = _text(row, 'codigo')
    if db.execute('SELECT 1 FROM materials WHERE LOWER(code)=LOWER(?)', (code,)).fetchone():
        _reject('codigo: material já cadastrado. Use uma ENTRADA para adicionar estoque; importação não sobrescreve materiais.')
    category = _lookup(db, 'categories', 'name', _text(row, 'categoria'), 'categoria')
    minimum = _amount(row, 'minimo', default=0)
    initial = _amount(row, 'saldo_inicial', default=0)
    values = callbacks['validate_entity'](db, 'materials', {
        'code': code, 'description': _text(row, 'descricao'), 'category_id': category['id'],
        'unit': _text(row, 'unidade').upper(), 'minimum_stock': str(minimum),
        'individualizable': False, 'status': 'ATIVO',
    })
    key = db.execute(
        f"INSERT INTO materials({','.join(values)}) VALUES({','.join('?' for _ in values)}) RETURNING id",
        tuple(values.values()),
    ).fetchone()['id']
    callbacks['audit'](db, user['id'], 'CRIAR', 'materials', key, {
        **values, 'import_batch': batch_id, 'filename': filename, 'line': line,
    })
    movement = None
    if initial:
        destination = _lookup(db, 'locations', 'name', _text(row, 'local'), 'local')
        movement = callbacks['perform_movement'](db, {
            'type': 'ENTRADA', 'material_id': key, 'quantity': str(initial),
            'destination_id': destination['id'], 'notes': _notes(row, filename, batch_id, line),
            **_source(row),
        }, user)
    elif any(row.get(field) for field in ('local', 'tipo_origem', 'referencia')):
        _reject('saldo_inicial: preencha uma quantidade positiva para informar local e origem de estoque.')
    return key, movement


def _movement(db, row, user, callbacks, filename, batch_id, line):
    kind = _text(row, 'tipo').upper()
    if kind not in ('ENTRADA', 'SAIDA', 'TRANSFERENCIA', 'DEVOLUCAO'):
        _reject('tipo: use ENTRADA, SAIDA, TRANSFERENCIA ou DEVOLUCAO. Ajustes exigem revisão individual por administrador.')
    material = _lookup(db, 'materials', 'code', _text(row, 'codigo_material'), 'codigo_material')
    data = {
        'type': kind, 'material_id': material['id'],
        'quantity': str(_amount(row, 'quantidade', positive=True)),
        'notes': _notes(row, filename, batch_id, line),
    }
    for column, needed in (('origem', kind in ('SAIDA', 'TRANSFERENCIA')), ('destino', kind in ('ENTRADA', 'TRANSFERENCIA', 'DEVOLUCAO'))):
        if needed:
            data['origin_id' if column == 'origem' else 'destination_id'] = _lookup(
                db, 'locations', 'name', _text(row, column), column,
            )['id']
        elif row.get(column):
            _reject(f'{column}: coluna não se aplica ao tipo {kind}.')
    if row.get('matricula'):
        data['employee_id'] = _lookup(db, 'employees', 'registration', _text(row, 'matricula'), 'matricula')['id']
    if kind == 'SAIDA':
        purpose = _text(row, 'finalidade').upper()
        if purpose not in ('CONSUMO', 'EMPRESTIMO'):
            _reject('finalidade: SAIDA exige CONSUMO ou EMPRESTIMO; o vínculo com funcionário não define a finalidade.')
        if purpose == 'EMPRESTIMO' and not data.get('employee_id'):
            _reject('matricula: empréstimo exige funcionário responsável.')
        data['purpose'] = purpose
    elif row.get('finalidade'):
        _reject('finalidade: preencha somente para SAIDA.')
    if kind == 'ENTRADA':
        data.update(_source(row))
    elif row.get('tipo_origem') or row.get('referencia'):
        _reject('tipo_origem e referencia: preencha somente para ENTRADA.')
    if kind in ('ENTRADA', 'TRANSFERENCIA') and data.get('employee_id'):
        _reject('matricula: preencha somente para SAIDA ou DEVOLUCAO.')
    return None, callbacks['perform_movement'](db, data, user)


def _apply_rows(db, entity, rows, user, callbacks, filename, batch_id):
    errors, warnings, details, materials, movements, seen = [], [], [], [], [], set()
    for row in rows:
        index = row.source_row
        fingerprint = tuple(sorted(row.items()))
        db.execute('SAVEPOINT compac_import_row')
        try:
            if fingerprint in seen:
                _reject('Linha duplicada no arquivo. Remova a repetição antes de importar.')
            seen.add(fingerprint)
            material, movement = (_material if entity == 'materials' else _movement)(
                db, row, user, callbacks, filename, batch_id, index,
            )
        except (HTTPException, sqlite3.IntegrityError, psycopg.IntegrityError) as exc:
            db.execute('ROLLBACK TO SAVEPOINT compac_import_row')
            message = exc.detail if isinstance(exc, HTTPException) else 'Código duplicado ou vínculo inválido. Confira os dados da linha.'
            errors.append({'row': index, 'message': str(message)})
            details.append({'row': index, 'status': 'ERRO', 'data': row})
        else:
            if material is not None:
                materials.append(material)
            if movement is not None:
                movements.append(movement)
            details.append({'row': index, 'status': 'VALIDA', 'data': row})
            if entity == 'movements' and row.get('tipo', '').upper() == 'DEVOLUCAO':
                warnings.append({'row': index, 'message': 'A devolução abate as pendências mais antigas do funcionário (FIFO); não identifica uma retirada específica.'})
            if any('http://' in value.lower() or 'https://' in value.lower() for value in row.values()):
                warnings.append({'row': index, 'message': 'Links são registrados apenas como texto de referência; nenhum documento é acessado ou lido por OCR.'})
        finally:
            db.execute('RELEASE SAVEPOINT compac_import_row')
    return errors, warnings, details, materials, movements


def register_import_routes(app, callbacks):
    """Register routes with injected legacy auth, transaction and stock services."""
    operator = callbacks['operator']

    def actor(db, request):
        return callbacks['transaction_actor'](db, request, roles=('ADMIN', 'OPERADOR'), at=callbacks['now']())

    def preview_operation(entity, data, request):
        _entity(entity)
        filename, content, digest = _upload(data)
        rows = _table(entity, content, filename)
        with callbacks['connect'](write=True) as db:
            user = actor(db, request)
            db.execute('SAVEPOINT compac_import_preview')
            try:
                errors, warnings, details, _, _ = _apply_rows(db, entity, rows, user, callbacks, filename, 'PREVIA')
            finally:
                db.execute('ROLLBACK TO SAVEPOINT compac_import_preview')
                db.execute('RELEASE SAVEPOINT compac_import_preview')
            token, claims = (None, None) if errors else _issue_token(user['id'], entity, digest, filename)
        return {
            'entity': entity, 'filename': filename, 'total_rows': len(rows),
            'valid_rows': len(rows) - len(errors), 'errors': errors, 'warnings': warnings,
            'rows': details, 'preview_token': token,
            'expires_at': datetime.fromtimestamp(claims['expires'], timezone.utc).isoformat() if claims else None,
        }

    def confirm_operation(entity, data, request, initial_user):
        _entity(entity)
        filename, content, digest = _upload(data, confirming=True)
        key = validate_key(request.headers.get('Idempotency-Key'))
        claims = _verify_token(data.get('preview_token'), initial_user['id'], entity, digest, filename)
        payload = {
            'filename': filename, 'sha256': digest, 'preview_token': data['preview_token'],
            'raw_payload_sha256': hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
        }
        with callbacks['connect'](write=True) as db:
            user = actor(db, request)  # Revoke access before either cache lookup.
            _verify_token(data['preview_token'], user['id'], entity, digest, filename)

            def execute():
                rows = _table(entity, content, filename)
                batch_id = claims['nonce']
                errors, _, _, materials, movements = _apply_rows(db, entity, rows, user, callbacks, filename, batch_id)
                if errors:
                    _reject({'message': 'Importação cancelada; nenhuma linha foi gravada. Gere uma nova prévia.', 'errors': errors})
                result = {
                    'entity': entity, 'imported_rows': len(rows), 'material_ids': materials,
                    'movement_ids': movements, 'batch_id': batch_id,
                }
                callbacks['audit'](db, user['id'], 'IMPORTAR', entity, details={
                    **result, 'filename': filename, 'sha256': digest,
                })
                return result

            return replay_or_execute(
                db, user['id'], f'POST /api/import/{entity}/confirm', key, payload,
                lambda: replay_or_execute(
                    db, user['id'], f'POST /api/import/{entity}/preview', claims['nonce'], payload, execute,
                ),
            )

    @app.post('/api/import/{entity}/preview')
    async def import_preview(entity: str, request: Request, user=Depends(operator)):
        data = await _json_body(request)
        return await run_in_threadpool(preview_operation, entity, data, request)

    @app.post('/api/import/{entity}/confirm')
    async def import_confirm(entity: str, request: Request, user=Depends(operator)):
        data = await _json_body(request)
        return await run_in_threadpool(confirm_operation, entity, data, request, user)

    @app.get('/api/import/{entity}/template')
    def import_template(entity: str, format: str = 'csv', user=Depends(operator)):
        from .document_formats import render_document

        _entity(entity)
        if format not in ('csv', 'xlsx'):
            _reject('Modelo disponível em CSV ou XLSX.')
        columns = [(name, name) for name in _COLUMNS[entity]]
        data, media_type, extension = render_document(
            format, 'Modelo de importação', columns, [], {'template': True},
        )
        return Response(data, media_type=media_type, headers={
            'Content-Disposition': f'attachment; filename="modelo-{entity}.{extension}"',
            'Cache-Control': 'no-store',
        })
