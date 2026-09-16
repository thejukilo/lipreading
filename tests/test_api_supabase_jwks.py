"""Supabase asymmetric (ES256 / JWKS) token verification."""

from __future__ import annotations

import importlib
import sys
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@pytest.fixture()
def keypair():
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv_pem, pub_pem


def _es256_token(priv_pem, sub="aaaa-es256", email="es@example.com", name="Es"):
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "email": email, "aud": "authenticated", "iat": now,
         "exp": now + 3600, "user_metadata": {"name": name}},
        priv_pem, algorithm="ES256", headers={"kid": "test-key-1"})


@pytest.fixture()
def client(tmp_path, monkeypatch, keypair):
    priv_pem, pub_pem = keypair
    monkeypatch.setenv("LIPREADING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIPREADING_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("LIPREADING_DISABLE_WORKER", "1")
    # Turns on Supabase mode + derives a JWKS URL (we stub the client below).
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    for mod in list(sys.modules):
        if mod.startswith("server.api"):
            del sys.modules[mod]
    main = importlib.import_module("server.api.main")
    security = importlib.import_module("server.api.security")

    class _FakeKey:
        def __init__(self, k): self.key = k

    class _FakeClient:
        def get_signing_key_from_jwt(self, token): return _FakeKey(pub_pem)

    monkeypatch.setattr(security, "_jwk_client", lambda: _FakeClient())

    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def test_es256_token_verifies_and_provisions(client, keypair):
    priv_pem, _ = keypair
    t = _es256_token(priv_pem)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "es@example.com"
    assert r.json()["display_name"] == "Es"


def test_es256_token_from_other_key_rejected(client):
    other = ec.generate_private_key(ec.SECP256R1())
    other_pem = other.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    t = _es256_token(other_pem)  # signed by a key the stub won't match
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 401
