"""Database engine + session wiring (SQLAlchemy 2.x, sync).

SQLite for local dev, Postgres in the cloud — the only difference is
``LIPREADING_DB_URL``. Models are declared against ``Base`` in ``models.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_URL


class Base(DeclarativeBase):
    pass


# check_same_thread=False: FastAPI serves requests on a threadpool; the session
# is still per-request so this is safe. Ignored by non-SQLite backends.
_connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=_connect_args, future=True)
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
