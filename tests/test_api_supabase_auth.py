"""Supabase-mode auth: verify Supabase-issued JWTs and provision users."""

from __future__ import annotations

import importlib
import sys
import time

import jwt
import pytest

SECRET = "super-secret-supabase-jwt-signing-key-000000"


def _supabase_token(sub="11111111-2222-3333-4444-555555555555",
                    email="lode@example.com", name="Lode", secret=SECRET, aud="authenticated"):
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "email": email, "aud": aud, "iat": now, "exp": now + 3600,
         "user_metadata": {"name": name}},
        secret, algorithm="HS256")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LIPREADING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIPREADING_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("LIPREADING_DISABLE_WORKER", "1")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    for mod in list(sys.modules):
        if mod.startswith("server.api"):
            del sys.modules[mod]
    main = importlib.import_module("server.api.main")
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


def test_supabase_token_provisions_user(client):
    t = _supabase_token()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "11111111-2222-3333-4444-555555555555"
    assert body["email"] == "lode@example.com"
    assert body["display_name"] == "Lode"


def test_same_subject_is_same_user(client):
    t = _supabase_token()
    id1 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"}).json()["id"]
    # A fresh token for the same subject must not create a second user.
    t2 = _supabase_token()
    id2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t2}"}).json()["id"]
    assert id1 == id2


def test_token_signed_with_wrong_secret_rejected(client):
    bad = _supabase_token(secret="not-the-real-secret-aaaaaaaaaaaaaaaaaaaa")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


def test_wrong_audience_rejected(client):
    bad = _supabase_token(aud="some-other-audience")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


def test_missing_token_rejected(client):
    assert client.get("/api/auth/me").status_code == 401


def test_two_supabase_users_isolated(client):
    ta = _supabase_token(sub="aaaaaaaa-0000-0000-0000-000000000001", email="a@x.com")
    tb = _supabase_token(sub="bbbbbbbb-0000-0000-0000-000000000002", email="b@x.com")
    ida = client.get("/api/auth/me", headers={"Authorization": f"Bearer {ta}"}).json()["id"]
    idb = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tb}"}).json()["id"]
    assert ida != idb
