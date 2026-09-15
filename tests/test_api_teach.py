"""Phase D tests: teach ingest, auto-retrain threshold, and job processing.

Uses a fake TeachStore (no cv2) and a fake trainer (no torch); the worker thread
is disabled so we drive process_job() deterministically.
"""

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
    monkeypatch.setenv("LIPREADING_RETRAIN_THRESHOLD", "4")
    monkeypatch.setenv("LIPREADING_DISABLE_WORKER", "1")
    for mod in list(sys.modules):
        if mod.startswith("server.api"):
            del sys.modules[mod]
    main = importlib.import_module("server.api.main")
    from fastapi.testclient import TestClient

    from server.api.training import TeachStore, get_teach_store

    class FakeTeach(TeachStore):
        def add_sample(self, user_id, phrase, frame_blobs, fps=25):
            return f"/fake/{user_id}/{phrase}.npz", max(len(frame_blobs), 8)

    main.app.dependency_overrides[get_teach_store] = lambda: FakeTeach()
    with TestClient(main.app) as c:
        yield c, main
    main.app.dependency_overrides.clear()


def _reg(c, email="a@b.com"):
    t = c.post("/api/auth/register",
               json={"email": email, "password": "password123", "display_name": "A"})
    return {"Authorization": f"Bearer {t.json()['access_token']}"}


def _frames(n):
    return [("frames", (f"f{i}.jpg", b"jpeg", "image/jpeg")) for i in range(n)]


def _add(c, h, phrase="hello there"):
    return c.post("/api/teach/samples", headers=h, data={"phrase": phrase}, files=_frames(10))


def test_sentences_endpoint(ctx):
    c, _ = ctx
    r = c.get("/api/teach/sentences?n=5")
    assert r.status_code == 200
    s = r.json()["sentences"]
    assert len(s) == 5 and len(set(s)) == 5


def test_add_sample_counts_and_no_trigger_below_threshold(ctx):
    c, _ = ctx
    h = _reg(c)
    r = _add(c, h, "one")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["samples_total"] == 1
    assert body["new_since_train"] == 1
    assert body["training_triggered"] is False


def test_auto_retrain_triggers_at_threshold(ctx):
    c, _ = ctx
    h = _reg(c)
    triggers = [_add(c, h, f"phrase {i}").json()["training_triggered"] for i in range(4)]
    # threshold=4 and MIN_TRAIN_SAMPLES=4 -> only the 4th enqueues
    assert triggers == [False, False, False, True]
    st = c.get("/api/teach/status", headers=h).json()
    assert st["retrain_threshold"] == 4
    assert st["latest_job"]["status"] in ("queued", "running", "done")


def test_train_now_requires_min_samples(ctx):
    c, _ = ctx
    h = _reg(c)
    _add(c, h, "only one")
    r = c.post("/api/teach/train", headers=h)
    assert r.status_code == 400  # fewer than 4 samples


def test_train_now_force_enqueues(ctx):
    c, _ = ctx
    h = _reg(c)
    for i in range(4):
        _add(c, h, f"p{i}")
    # already auto-enqueued at #4; force returns the existing/queued job
    r = c.post("/api/teach/train", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "running", "done")


def test_process_job_success_activates_private_model(ctx):
    c, main = ctx
    h = _reg(c)
    for i in range(4):
        _add(c, h, f"p{i}")
    user_id = c.get("/api/auth/me", headers=h).json()["id"]

    from server.api.db import SessionLocal
    from server.api.models import TrainingJob
    from server.api.training import process_job
    from sqlalchemy import select

    def fake_trainer(user, store, base, out_path, on_progress=None):
        if on_progress:
            on_progress("training…")
        with open(out_path, "wb") as f:
            f.write(b"fake-checkpoint")
        return out_path

    db = SessionLocal()
    try:
        job = db.scalar(select(TrainingJob).where(TrainingJob.user_id == user_id))
        assert job is not None and job.status == "queued"
        done = process_job(db, job, fake_trainer)
        assert done.status == "done"
        assert done.result_model_id
    finally:
        db.close()

    st = c.get("/api/teach/status", headers=h).json()
    assert st["active_model_id"] is not None
    assert st["new_since_train"] == 0          # samples consumed
    assert st["latest_job"]["status"] == "done"


def test_process_job_failure_records_error(ctx):
    c, main = ctx
    h = _reg(c)
    for i in range(4):
        _add(c, h, f"p{i}")
    user_id = c.get("/api/auth/me", headers=h).json()["id"]

    from server.api.db import SessionLocal
    from server.api.models import TrainingJob
    from server.api.training import process_job
    from sqlalchemy import select

    def boom(user, store, base, out_path, on_progress=None):
        raise RuntimeError("gpu on fire")

    db = SessionLocal()
    try:
        job = db.scalar(select(TrainingJob).where(TrainingJob.user_id == user_id))
        done = process_job(db, job, boom)
        assert done.status == "failed"
        assert "gpu on fire" in done.error
    finally:
        db.close()

    st = c.get("/api/teach/status", headers=h).json()
    assert st["active_model_id"] is None       # unchanged on failure
    assert st["new_since_train"] == 4          # samples NOT consumed


def test_teach_status_isolated_between_users(ctx):
    c, _ = ctx
    ha = _reg(c, "a@b.com")
    hb = _reg(c, "b@b.com")
    _add(c, ha, "a-phrase")
    assert c.get("/api/teach/status", headers=hb).json()["samples_total"] == 0
    assert c.get("/api/teach/status", headers=ha).json()["samples_total"] == 1


def test_list_and_delete_sample(ctx):
    c, _ = ctx
    h = _reg(c)
    _add(c, h, "keep this")
    bad = _add(c, h, "off camera oops").json()["sample_id"]
    rows = c.get("/api/teach/samples", headers=h).json()
    assert {r["phrase"] for r in rows} == {"keep this", "off camera oops"}

    r = c.delete(f"/api/teach/samples/{bad}", headers=h)
    assert r.status_code == 204
    rows = c.get("/api/teach/samples", headers=h).json()
    assert [r["phrase"] for r in rows] == ["keep this"]
    assert c.get("/api/teach/status", headers=h).json()["samples_total"] == 1


def test_delete_sample_is_owner_scoped(ctx):
    c, _ = ctx
    ha = _reg(c, "a@b.com")
    hb = _reg(c, "b@b.com")
    sid = _add(c, ha, "mine").json()["sample_id"]
    # B cannot delete or see A's recording
    assert c.delete(f"/api/teach/samples/{sid}", headers=hb).status_code == 404
    assert c.get("/api/teach/samples", headers=hb).json() == []
    assert c.get("/api/teach/samples", headers=ha).json()[0]["phrase"] == "mine"
