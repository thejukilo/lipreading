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


_jwks_client = None


def _jwk_client():
    """Cached PyJWKClient for Supabase's public signing keys (asymmetric)."""
    global _jwks_client
    if _jwks_client is None:
        from .config import SUPABASE_JWKS_URL

        if not SUPABASE_JWKS_URL:
            return None
        _jwks_client = jwt.PyJWKClient(SUPABASE_JWKS_URL)
    return _jwks_client


def verify_supabase_token(token: str) -> dict | None:
    """Verify a Supabase access token; return its claims, or None.

    Supports both signing schemes:
    - asymmetric (ES256/RS256) — verified against the project JWKS (public keys);
    - legacy HS256 — verified with the shared JWT secret.
    The token header's ``alg`` selects the path.
    """
    from .config import SUPABASE_JWT_AUD, SUPABASE_JWT_SECRET

    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError:
        return None

    try:
        if alg == "HS256":
            if not SUPABASE_JWT_SECRET:
                return None
            return jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"],
                              audience=SUPABASE_JWT_AUD)
        # Asymmetric: fetch the matching public key by 'kid' from the JWKS.
        client = _jwk_client()
        if client is None:
            return None
        key = client.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256"],
                          audience=SUPABASE_JWT_AUD)
    except jwt.PyJWTError:
        return None
    except Exception:
        # JWKS fetch failure etc. — treat as unverifiable rather than 500.
        return None
