"""Runtime configuration for the multi-user backend.

Everything is read from environment variables with local-friendly defaults so it
runs on your PC with zero setup, yet moves to the cloud by only changing env
vars (e.g. a Postgres ``LIPREADING_DB_URL`` and a fixed ``LIPREADING_JWT_SECRET``).

Nothing secret is hard-coded: the JWT secret defaults to a persisted random key
so tokens survive restarts in dev without you configuring anything.
"""

from __future__ import annotations

import os
import secrets

# Where the DB file and per-user media live. One directory keeps the whole app
# state relocatable/back-uppable.
DATA_DIR = os.environ.get(
    "LIPREADING_DATA_DIR",
    os.path.join(os.path.expanduser("~"), ".lipreading", "server"),
)
MEDIA_DIR = os.path.join(DATA_DIR, "media")     # per-user audio/video + models


def _default_db_url() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return "sqlite:///" + os.path.join(DATA_DIR, "lipreading.db")


DB_URL = os.environ.get("LIPREADING_DB_URL") or _default_db_url()


def _persisted_secret() -> str:
    """A stable JWT secret for local dev: read env, else a key file we create
    once (so restarting the server doesn't invalidate everyone's login)."""
    env = os.environ.get("LIPREADING_JWT_SECRET")
    if env:
        return env
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "jwt_secret.txt")
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read().strip()
        if s:
            return s
    except OSError:
        pass
    s = secrets.token_urlsafe(48)
    try:
        # 0600 so other local users can't read it; best-effort on Windows.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(s)
    except OSError:
        pass
    return s


JWT_SECRET = _persisted_secret()
JWT_ALG = "HS256"
JWT_TTL_SECONDS = int(os.environ.get("LIPREADING_JWT_TTL", str(30 * 24 * 3600)))  # 30 days

# How many *new* recorded sentences trigger an automatic background retrain.
RETRAIN_THRESHOLD = int(os.environ.get("LIPREADING_RETRAIN_THRESHOLD", "10"))
