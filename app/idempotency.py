"""Replay committed stock operations without duplicating their effects."""

import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException


KEY_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', re.ASCII)


def validate_key(value):
    if not isinstance(value, str) or KEY_PATTERN.fullmatch(value) is None:
        raise HTTPException(
            422,
            'Informe Idempotency-Key com 1 a 128 caracteres: letras, números, ponto, hífen, sublinhado ou dois-pontos.',
        )
    return value


def replay_or_execute(db, user_id, scope, key, payload, operation):
    """Caller must hold connect(write=True) until this function commits or fails.

    The existing SQLite write transaction/PostgreSQL advisory lock serializes
    lookup and effects. The composite primary key additionally guards storage.
    There is deliberately no automatic expiry: deleting a key permits a repeat.
    """
    key = validate_key(key)
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise HTTPException(422, 'O conteúdo da operação não é um JSON válido.')
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    identity = (user_id, scope, key)
    previous = db.execute(
        'SELECT request_hash,response_json FROM idempotency_requests WHERE user_id=? AND scope=? AND idempotency_key=?',
        identity,
    ).fetchone()
    if previous:
        if previous['request_hash'] != fingerprint:
            raise HTTPException(409, 'Esta Idempotency-Key já foi usada com dados diferentes. Confira a operação original.')
        return json.loads(previous['response_json'])

    result = operation()
    response = json.dumps(result, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    db.execute(
        'INSERT INTO idempotency_requests(user_id,scope,idempotency_key,request_hash,response_json,created_at) VALUES(?,?,?,?,?,?)',
        (*identity, fingerprint, response, datetime.now(timezone.utc).isoformat()),
    )
    return result
