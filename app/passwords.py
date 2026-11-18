"""Password primitives shared by entrypoints without importing application routes."""
import hashlib
import hmac
import secrets


def hash_password(value):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()


def verify_password(value, encoded):
    salt, digest = encoded.split(':')
    derived = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(derived.hex(), digest)
