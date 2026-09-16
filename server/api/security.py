"""Password hashing + JWT session tokens.

Passwords: bcrypt, but pre-hashed with SHA-256 so inputs longer than bcrypt's
72-byte limit are still fully mixed in (a well-known bcrypt footgun). Stored as
the standard bcrypt string; nothing here is reversible.

Sessions: short JWTs signed HS256 with the persisted server secret.
"""

from __future__ import annotations

import base64
import hashlib
import time

import bcrypt
import jwt

from .config import JWT_ALG, JWT_SECRET, JWT_TTL_SECONDS


def _prehash(password: str) -> bytes:
    # base64(sha256(pw)) is 44 bytes (< 72) and depends on every input byte.
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, ttl: int = JWT_TTL_SECONDS) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> str | None:
    """Return the user id, or None if the token is invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def verify_supabase_token(token: str) -> dict | None:
    """Verify a Supabase-issued JWT (HS256, aud='authenticated'); return claims.

    Supabase signs access tokens with the project's JWT secret. If the project
    uses asymmetric (RS/ES) keys instead, this returns None and JWKS
    verification would be needed — not wired yet.
    """
    from .config import SUPABASE_JWT_AUD, SUPABASE_JWT_SECRET

    if not SUPABASE_JWT_SECRET:
        return None
    try:
        return jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"],
                          audience=SUPABASE_JWT_AUD)
    except jwt.PyJWTError:
        return None
