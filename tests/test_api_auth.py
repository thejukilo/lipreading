"""Phase A backend tests: auth + isolation. No ML deps required.

Runs each test against a fresh temp SQLite DB by pointing the app's env at a
tmp dir *before* importing the app modules.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point all state at a throwaway dir and force a fresh module import so the
    # engine binds to this DB (config/db read env at import time).
    monkeypatch.setenv("LIPREADING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIPREADING_DB_URL", f"sqlite:///{tmp_path/'test.db'}")
    monkeypatch.setenv("LIPREADING_JWT_SECRET", "test-secret-key-at-least-32-bytes-long!!")
    for mod in list(sys.modules):
        if mod.startswith("server.api"):
            del sys.modules[mod]
    main = importlib.import_module("server.api.main")
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


def _register(client, email="a@b.com", pw="password123", name="Al"):
    return client.post("/api/auth/register",
                       json={"email": email, "password": pw, "display_name": name})


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_register_returns_token_and_me_works(client):
    r = _register(client)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    assert token
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "a@b.com"
    assert body["display_name"] == "Al"
    assert body["default_voice_id"] is None


def test_duplicate_email_rejected(client):
    assert _register(client).status_code == 201
    r = _register(client, name="Al again")
    assert r.status_code == 409


def test_email_is_case_insensitive(client):
    assert _register(client, email="Al@B.com").status_code == 201
    # login with different casing works
    r = client.post("/api/auth/login", json={"email": "al@b.com", "password": "password123"})
    assert r.status_code == 200
    # and re-register with different casing is a conflict
    assert _register(client, email="AL@B.COM").status_code == 409


def test_login_wrong_password_401(client):
    _register(client)
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "nope-nope-nope"})
    assert r.status_code == 401


def test_login_unknown_email_401(client):
    r = client.post("/api/auth/login", json={"email": "ghost@b.com", "password": "whatever12"})
    assert r.status_code == 401


def test_me_requires_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me",
                      headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/api/auth/me",
                      headers={"Authorization": "Basic xyz"}).status_code == 401


def test_short_password_rejected(client):
    r = client.post("/api/auth/register",
                    json={"email": "x@y.com", "password": "short", "display_name": ""})
    assert r.status_code == 422  # pydantic min_length


def test_two_users_get_distinct_identities(client):
    t1 = _register(client, email="one@b.com").json()["access_token"]
    t2 = _register(client, email="two@b.com").json()["access_token"]
    id1 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t1}"}).json()["id"]
    id2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t2}"}).json()["id"]
    assert id1 != id2
