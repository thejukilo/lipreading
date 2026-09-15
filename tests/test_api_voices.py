"""Phase C tests: per-user voices (upload/list/default/reference/delete + isolation)."""

from __future__ import annotations

import importlib
import io
import sys

import numpy as np
import pytest
import soundfile as sf


def _wav_bytes(sr=16000, secs=0.4) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, (0.1 * np.sin(np.arange(int(sr * secs)) * 0.1)).astype("float32"),
             sr, format="WAV")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LIPREADING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIPREADING_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("LIPREADING_JWT_SECRET", "x" * 40)
    for mod in list(sys.modules):
        if mod.startswith("server.api"):
            del sys.modules[mod]
    main = importlib.import_module("server.api.main")
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


def _reg(client, email="a@b.com"):
    t = client.post("/api/auth/register",
                    json={"email": email, "password": "password123", "display_name": "A"})
    return {"Authorization": f"Bearer {t.json()['access_token']}"}


def _upload(client, headers, name="My Voice"):
    return client.post("/api/voices", headers=headers,
                       data={"name": name},
                       files={"audio": ("v.wav", _wav_bytes(), "audio/wav")})


def test_first_voice_becomes_default(client):
    h = _reg(client)
    r = _upload(client, h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "My Voice"
    assert body["is_default"] is True
    assert body["engine"] == "voxcpm"


def test_list_and_second_voice_not_default_until_set(client):
    h = _reg(client)
    v1 = _upload(client, h, "One").json()
    v2 = _upload(client, h, "Two").json()
    assert v2["is_default"] is False

    lst = client.get("/api/voices", headers=h).json()
    assert {v["name"] for v in lst} == {"One", "Two"}

    r = client.post(f"/api/voices/{v2['id']}/default", headers=h)
    assert r.status_code == 200 and r.json()["is_default"] is True
    # v1 no longer default
    lst = {v["id"]: v for v in client.get("/api/voices", headers=h).json()}
    assert lst[v1["id"]]["is_default"] is False
    assert lst[v2["id"]]["is_default"] is True


def test_reference_download(client):
    h = _reg(client)
    v = _upload(client, h).json()
    r = client.get(f"/api/voices/{v['id']}/reference", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"  # a real WAV


def test_delete_default_falls_back_to_other(client):
    h = _reg(client)
    v1 = _upload(client, h, "One").json()
    v2 = _upload(client, h, "Two").json()
    client.post(f"/api/voices/{v1['id']}/default", headers=h)
    assert client.delete(f"/api/voices/{v1['id']}", headers=h).status_code == 204
    # default fell back to the remaining voice
    me = client.get("/api/auth/me", headers=h).json()
    assert me["default_voice_id"] == v2["id"]


def test_non_wav_upload_rejected(client):
    h = _reg(client)
    r = client.post("/api/voices", headers=h, data={"name": "Bad"},
                    files={"audio": ("x.txt", b"not audio at all", "text/plain")})
    assert r.status_code == 400


def test_invalid_engine_rejected(client):
    h = _reg(client)
    r = client.post("/api/voices", headers=h, data={"name": "X", "engine": "bogus"},
                    files={"audio": ("v.wav", _wav_bytes(), "audio/wav")})
    assert r.status_code == 422


def test_voices_are_isolated_between_users(client):
    ha = _reg(client, "a@b.com")
    hb = _reg(client, "b@b.com")
    va = _upload(client, ha, "A-voice").json()
    # B cannot see A's voice in their list
    assert client.get("/api/voices", headers=hb).json() == []
    # B cannot download or delete A's voice
    assert client.get(f"/api/voices/{va['id']}/reference", headers=hb).status_code == 404
    assert client.delete(f"/api/voices/{va['id']}", headers=hb).status_code == 404
    # A's voice still intact
    assert client.get(f"/api/voices/{va['id']}/reference", headers=ha).status_code == 200
