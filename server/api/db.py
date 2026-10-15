"""Database engine + session wiring (SQLAlchemy 2.x, sync).

SQLite for local dev, Postgres in the cloud — the only difference is
``LIPREADING_DB_URL``. Models are declared against ``Base`` in ``models.py``.

If a non-SQLite URL is configured but unreachable at startup (wrong host,
project paused, offline), we fall back to a local SQLite file rather than
crashing the whole server — so auth/testing still works.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_URL


class Base(DeclarativeBase):
    pass


_FALLBACK_URL = "sqlite:///lipreading_local.db"


def _make_engine(url: str):
    # check_same_thread=False: FastAPI serves requests on a threadpool; the
    # session is still per-request so this is safe. Ignored by non-SQLite.
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=args, future=True, pool_pre_ping=True)


_url = DB_URL
engine = _make_engine(_url)

# For a remote DB, verify it actually connects; otherwise fall back to SQLite
# so a bad/unreachable LIPREADING_DB_URL doesn't take the whole server down.
if not _url.startswith("sqlite"):
    try:
        with engine.connect() as _c:
            _c.execute(text("SELECT 1"))
    except Exception as _e:  # noqa: BLE001
        print(f"[db] could not connect to configured database "
              f"({type(_e).__name__}): {_e}")
        print(f"[db] falling back to local SQLite at {_FALLBACK_URL}. "
              f"Set a working LIPREADING_DB_URL to use Postgres.")
        try:
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass
        _url = _FALLBACK_URL
        engine = _make_engine(_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                            class_=Session, future=True)


def init_db() -> None:
    """Create tables if they don't exist. Called at app startup."""
    from . import models  # noqa: F401  (register mappers before create_all)

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: a request-scoped session, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
