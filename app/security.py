"""Origin validation and shared, short-lived credential failure limits."""
import hashlib
import time
from urllib.parse import urlsplit


FAILURE_WINDOW_SECONDS = 300
ACCOUNT_FAILURE_LIMIT = 10
ORIGIN_FAILURE_LIMIT = 30


def origin(value, *, referer=False):
    """Return a normalized HTTP origin, rejecting credentials and malformed URLs."""
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if '\\' in value or any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        port = parsed.port
        if not referer and (parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            return None
    except ValueError:
        return None
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    if port is not None and port != (443 if parsed.scheme == 'https' else 80):
        host += ':' + str(port)
    return parsed.scheme + '://' + host


def mutation_origin_allowed(request, expected):
    """Keep header-only CLI compatibility without loosening browser CORS rules."""
    if request.headers.get('x-compac-client') != 'web':
        return False
    trusted = origin(expected)
    if trusted is None:
        return False
    fetch_site = request.headers.get('sec-fetch-site')
    if fetch_site is not None and fetch_site != 'same-origin':
        return False
    supplied = request.headers.get('origin')
    if supplied is not None:
        return origin(supplied) == trusted
    referer = request.headers.get('referer')
    if referer is not None:
        return origin(referer, referer=True) == trusted
    # Legacy non-browser clients must explicitly send the custom header and
    # authenticate normally. The header is neither a credential nor an origin.
    return True


def credential_keys(username, request):
    account = username.strip().casefold()
    # Never trust attacker-supplied forwarded IP headers. Deployment proxy
    # topology must be verified before enabling trusted proxy processing.
    host = request.client.host if request.client else 'unknown'
    return tuple(hashlib.sha256(value.encode()).hexdigest() for value in (account, host))


def failure_state(db, account_hash, origin_hash):
    timestamp = int(time.time())
    cutoff = timestamp - FAILURE_WINDOW_SECONDS
    db.execute('DELETE FROM auth_attempts WHERE attempted_at<=?', (cutoff,))
    account_count = db.execute(
        'SELECT COUNT(*) FROM auth_attempts WHERE account_hash=? AND attempted_at>?',
        (account_hash, cutoff),
    ).fetchone()[0]
    origin_count = db.execute(
        'SELECT COUNT(*) FROM auth_attempts WHERE origin_hash=? AND attempted_at>?',
        (origin_hash, cutoff),
    ).fetchone()[0]
    return timestamp, account_count, origin_count


def limited(state):
    _, account_count, origin_count = state
    return account_count >= ACCOUNT_FAILURE_LIMIT or origin_count >= ORIGIN_FAILURE_LIMIT


def record_failure(db, account_hash, origin_hash, timestamp):
    db.execute(
        'INSERT INTO auth_attempts(account_hash,origin_hash,attempted_at) VALUES(?,?,?)',
        (account_hash, origin_hash, timestamp),
    )
