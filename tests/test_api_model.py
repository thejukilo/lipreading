"""Model info + base/personal switch endpoints."""

from __future__ import annotations

import importlib
import sys
from uuid import uuid4

import pytest


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("LIPREADING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIPREADING_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("LIPREADING_JWT_SECRET", "x" * 40)
    monkeypatch.setenv("LIPREADING_DISABLE_WORKER", "1")
    for mod in list(sys.modules):
        if mod.startswith("server.api"):
            del sys.modules[mod]
    main = importlib.import_module("server.api.main")
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c, main


def _reg(c):
    t = c.post("/api/auth/register",
               json={"email": "a@b.com", "password": "password123", "display_name": "A"})
    return {"Authorization": f"Bearer {t.json()['access_token']}"}


def test_info_defaults_to_base(ctx):
    c, _ = ctx
    h = _reg(c)
    r = c.get("/api/model/info", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "base"
    assert body["has_personal"] is False
    assert body["total_clips"] == 0


def test_select_personal_without_model_is_400(ctx):
    c, _ = ctx
    h = _reg(c)
    r = c.post("/api/model/select", headers=h, json={"use_personal": True})
    assert r.status_code == 400


def test_select_personal_then_base(ctx):
    c, main = ctx
    h = _reg(c)
    user_id = c.get("/api/auth/me", headers=h).json()["id"]

    # Insert a personal model directly.
    from server.api.db import SessionLocal
    from server.api.models import PersonalModel

    db = SessionLocal()
    try:
        db.add(PersonalModel(id=uuid4().hex, user_id=user_id, path="/tmp/m.pth",
                             base_checkpoint="base.pth", n_samples=12))
        db.commit()
    finally:
        db.close()

    info = c.get("/api/model/info", headers=h).json()
    assert info["has_personal"] is True
    assert info["n_samples"] == 12

    on = c.post("/api/model/select", headers=h, json={"use_personal": True}).json()
    assert on["active"] == "personal"
    assert c.get("/api/auth/me", headers=h).json()["active_model_id"] is not None

    off = c.post("/api/model/select", headers=h, json={"use_personal": False}).json()
    assert off["active"] == "base"
    assert c.get("/api/auth/me", headers=h).json()["active_model_id"] is None
