"""Shared FastAPI dependencies: DB session + current authenticated user.

Two auth modes:
- **Supabase** (cloud): when SUPABASE_JWT_SECRET is set, verify the Supabase
  access token and provision a local User row from its claims.
- **Custom** (local dev/tests): verify our own JWT and look the user up.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import supabase_enabled
from .db import get_db
from .models import User
from .security import decode_token, verify_supabase_token

_UNAUTH = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="invalid or expired token")


def _provision_supabase_user(db: Session, claims: dict) -> User:
    """Get-or-create the User for a verified Supabase token."""
    uid = claims["sub"]
    user = db.get(User, uid)
    if user is not None:
        return user
    meta = claims.get("user_metadata") or {}
    name = (meta.get("name") or meta.get("full_name") or "").strip()
    user = User(id=uid, email=(claims.get("email") or f"{uid}@users.local"),
                display_name=name, password_hash=None)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:      # raced with a concurrent request
        db.rollback()
        user = db.get(User, uid)
        if user is None:
            raise _UNAUTH
    return user


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token to a User (Supabase or custom), or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    if supabase_enabled():
        claims = verify_supabase_token(token)
        if not claims or not isinstance(claims.get("sub"), str):
            raise _UNAUTH
        return _provision_supabase_user(db, claims)

    # Local custom-auth fallback.
    user_id = decode_token(token)
    if not user_id:
        raise _UNAUTH
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="user no longer exists")
    return user
