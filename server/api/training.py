"""Teach ingest + background-training job logic.

Two concerns live here, both DB-driven and unit-testable without torch:

1. **Ingest** — turn an uploaded push-to-talk clip into a stored, labeled
   training sample (reusing the existing per-user ``TrainingStore``, which
   transparently falls back to ``.npz`` when no video codec is present).
2. **Jobs** — decide when to (re)train, and run a job: fine-tune the user's
   private model on *all* their samples from the shared base, register it, and
   activate it. The heavy ``finetune()`` call is injected as ``trainer`` so
   tests substitute a fake; the real one runs on the user's GPU.
"""

from __future__ import annotations

import os
import threading
import time
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import RETRAIN_THRESHOLD
from .models import PersonalModel, TrainingJob, TrainingSample, User
from .storage import models_dir, training_dir

MIN_TRAIN_SAMPLES = 4  # finetune() needs at least this many clips


# ---- per-user training store -------------------------------------------------

def user_training_store(user_id: str):
    from ..dataset import TrainingStore

    return TrainingStore(base_dir=training_dir(user_id))


# ---- ingest ------------------------------------------------------------------

class TeachStore:
    """Interface for storing an uploaded clip (overridden with a fake in tests)."""

    def add_sample(self, user_id: str, phrase: str, frame_blobs: list[bytes],
                   fps: int = 25) -> tuple[str, int]:
        raise NotImplementedError


class LocalTeachStore(TeachStore):
    def add_sample(self, user_id, phrase, frame_blobs, fps=25):
        from ..inference_service import decode_jpeg_frames

        arr = decode_jpeg_frames(frame_blobs, max_side=480)
        store = user_training_store(user_id)
        path = store.add_clip(phrase, arr, fps=fps, created=time.time())
        return path, int(arr.shape[0])


_teach_store: TeachStore | None = None


def get_teach_store() -> TeachStore:
    global _teach_store
    if _teach_store is None:
        _teach_store = LocalTeachStore()
    return _teach_store


# ---- job queue logic ---------------------------------------------------------

def count_samples(db: Session, user_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(TrainingSample)
                         .where(TrainingSample.user_id == user_id)) or 0)


def count_new_samples(db: Session, user_id: str) -> int:
    """Samples recorded since the last completed training (drives auto-retrain)."""
    return int(db.scalar(select(func.count()).select_from(TrainingSample)
                         .where(TrainingSample.user_id == user_id,
                                TrainingSample.consumed.is_(False))) or 0)


def active_job(db: Session, user_id: str) -> TrainingJob | None:
    return db.scalar(select(TrainingJob).where(
        TrainingJob.user_id == user_id,
        TrainingJob.status.in_(("queued", "running"))))


def enqueue_if_ready(db: Session, user_id: str, *, force: bool = False,
                     threshold: int = RETRAIN_THRESHOLD) -> TrainingJob | None:
    """Queue a training job when enough new samples exist (or force=True).

    Returns the new job, or None if not ready / one is already pending.
    """
    if active_job(db, user_id) is not None:
        return None
    total = count_samples(db, user_id)
    if total < MIN_TRAIN_SAMPLES:
        return None
    if not force and count_new_samples(db, user_id) < threshold:
        return None
    job = TrainingJob(id=uuid4().hex, user_id=user_id, status="queued", n_samples=total)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def process_job(db: Session, job: TrainingJob, trainer) -> TrainingJob:
    """Run one queued job to completion (or failure). ``trainer`` does the work.

    trainer(user, store, base_ckpt, out_path, on_progress) -> saved checkpoint path.
    """
    job.status = "running"
    job.started_at = time.time()
    db.add(job)
    db.commit()

    def progress(msg: str) -> None:
        # Append a short rolling log the UI can poll.
        job.log = (job.log or "") + msg.strip() + "\n"
        db.add(job)
        db.commit()

    try:
        from ..settings import load_config

        user = db.get(User, job.user_id)
        store = user_training_store(job.user_id)
        base = load_config().checkpoint
        out_path = os.path.join(models_dir(job.user_id), f"{job.id}.pth")
        path = trainer(user, store, base, out_path, progress)

        pm = PersonalModel(id=uuid4().hex, user_id=job.user_id, path=path,
                           base_checkpoint=base, n_samples=job.n_samples)
        db.add(pm)
        # Activate it for this user and mark every current sample as consumed.
        user.active_model_id = pm.id
        db.add(user)
        db.execute(update(TrainingSample)
                   .where(TrainingSample.user_id == job.user_id,
                          TrainingSample.consumed.is_(False))
                   .values(consumed=True))
        job.status = "done"
        job.result_model_id = pm.id
        job.finished_at = time.time()
        db.add(job)
        db.commit()
    except Exception as e:  # noqa: BLE001 - record failure, keep the queue alive
        db.rollback()
        job.status = "failed"
        job.error = str(e)
        job.finished_at = time.time()
        db.add(job)
        db.commit()
    return job


def default_trainer(user: User, store, base_ckpt: str, out_path: str, on_progress=None) -> str:
    """The real trainer: fine-tune the user's private model from the base."""
    from ..finetune import finetune
    from ..settings import load_config

    cfg = load_config()
    return finetune(store, checkpoint_path=base_ckpt, out_path=out_path,
                    auto_avsr_dir=cfg.auto_avsr_dir, detector=cfg.detector,
                    device=cfg.device, on_progress=on_progress)


# ---- background worker thread ------------------------------------------------

class TrainingWorker(threading.Thread):
    """Polls for queued jobs and runs them one at a time."""

    def __init__(self, trainer=None, poll: float = 2.0) -> None:
        super().__init__(daemon=True, name="training-worker")
        self._trainer = trainer or default_trainer
        self._poll = poll
        self._stop = threading.Event()

    def run(self) -> None:
        from .db import SessionLocal

        while not self._stop.wait(self._poll):
            try:
                db = SessionLocal()
                try:
                    job = db.scalar(select(TrainingJob)
                                    .where(TrainingJob.status == "queued")
                                    .order_by(TrainingJob.created_at))
                    if job is not None:
                        process_job(db, job, self._trainer)
                finally:
                    db.close()
            except Exception:
                pass  # never let the worker die on a transient error

    def stop(self) -> None:
        self._stop.set()
