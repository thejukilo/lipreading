"""Phase B tests: the /api/utter speak loop, with a fake speech service.

Verifies routing, auth, error mapping, the speak toggle, and that per-user
model/voice resolution is passed through — all without torch/cv2.
"""

from __future__ import annotations

import importlib
import sys

import pytest


class FakeSpeech:
    """Stand-in for LocalSpeechService: records calls, no real models."""

    def __init__(self):
        self.calls = []

    def transcribe(self, frame_blobs, fps=25, cleanup=True, model_path=None):
        from server.api.speech import TooFewFrames

        self.calls.append(("transcribe", len(frame_blobs), fps, cleanup, model_path))
        if len(frame_blobs) < 8:
            raise TooFewFrames(f"only {len(frame_blobs)} usable frame(s) — hold longer.")
        return "hello world"

    def synthesize_wav(self, text, voice_ref=None, prompt_text=None, engine="voxcpm"):
        self.calls.append(("synthesize", text, voice_ref, prompt_text, engine))
        return b"RIFFfake-wav-bytes"


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("LIPREADING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LIPREADING_DB_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("LIPREADING_JWT_SECRET", "x" * 40)
    for mod in list(sys.modules):
        if mod.startswith("server.api"):
            del sys.modules[mod]
    main = importlib.import_module("server.api.main")
    from fastapi.testclient import TestClient

    from server.api.speech import get_speech_service

    fake = FakeSpeech()
    main.app.dependency_overrides[get_speech_service] = lambda: fake
    with TestClient(main.app) as c:
        token = c.post("/api/auth/register",
                       json={"email": "a@b.com", "password": "password123",
                             "display_name": "Al"}).json()["access_token"]
        yield c, fake, {"Authorization": f"Bearer {token}"}
    main.app.dependency_overrides.clear()


def _frames(n, field="frames"):
    return [(field, (f"f{i}.jpg", b"jpegbytes", "image/jpeg")) for i in range(n)]


def test_utter_requires_auth(ctx):
    c, _, _ = ctx
    r = c.post("/api/utter", files=_frames(10))
    assert r.status_code == 401


def test_utter_happy_path_returns_text_and_audio(ctx):
    c, fake, h = ctx
    r = c.post("/api/utter", headers=h, files=_frames(12),
               data={"fps": "25", "speak": "true", "cleanup": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "hello world"
    assert body["audio"] is not None  # base64 of the fake wav
    import base64
    assert base64.b64decode(body["audio"]) == b"RIFFfake-wav-bytes"
    # base model + default voice for a fresh user
    assert ("transcribe", 12, 25, True, None) in fake.calls
    assert any(c[0] == "synthesize" and c[2] is None for c in fake.calls)


def test_utter_too_few_frames_400(ctx):
    c, _, h = ctx
    r = c.post("/api/utter", headers=h, files=_frames(3))
    assert r.status_code == 400
    assert "frame" in r.json()["detail"]


def test_utter_speak_false_skips_audio(ctx):
    c, fake, h = ctx
    r = c.post("/api/utter", headers=h, files=_frames(10), data={"speak": "false"})
    assert r.status_code == 200
    assert r.json()["audio"] is None
    assert not any(c[0] == "synthesize" for c in fake.calls)


def test_utter_cleanup_flag_passed_through(ctx):
    c, fake, h = ctx
    c.post("/api/utter", headers=h, files=_frames(10), data={"cleanup": "false"})
    assert fake.calls[0] == ("transcribe", 10, 25, False, None)
