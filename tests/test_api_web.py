"""Phase E: the PWA shell is served correctly by the API."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
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
        yield c


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Lipreading</title>" in r.text
    assert "/app.js" in r.text


def test_static_assets_served(client):
    js = client.get("/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert "/api/utter" in js.text  # the app talks to our endpoint

    man = client.get("/manifest.webmanifest")
    assert man.status_code == 200 and "manifest" in man.headers["content-type"]

    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]

    ico = client.get("/icon.svg")
    assert ico.status_code == 200 and "svg" in ico.headers["content-type"]
