"""Teach flow: get sentences, upload recorded clips, trigger + track training.

    GET  /api/teach/sentences        -> a batch of prompts to read
    POST /api/teach/samples          -> store one recorded clip (auto-retrains
                                        in the background once enough new ones)
    GET  /api/teach/status           -> counts + latest job
    POST /api/teach/train            -> force a training run now
"""

# No `from __future__ import annotations`: FastAPI needs real UploadFile/Form types.

from uuid import uuid4

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import TrainingJob, TrainingSample, User
from ..schemas import JobOut, SampleOut, SampleRow, SentencesOut, TeachStatusOut
from ..sentences import sample_sentences
from ..config import RETRAIN_THRESHOLD
from ..training import (
    TeachStore,
    count_new_samples,
    count_samples,
    enqueue_if_ready,
    get_teach_store,
    user_training_store,
)

router = APIRouter(prefix="/api/teach", tags=["teach"])


def _latest_job(db: Session, user_id: str) -> TrainingJob | None:
    return db.scalar(select(TrainingJob).where(TrainingJob.user_id == user_id)
                     .order_by(TrainingJob.created_at.desc()))


@router.get("/sentences", response_model=SentencesOut)
def sentences(n: int = Query(10, ge=1, le=30)) -> SentencesOut:
    return SentencesOut(sentences=sample_sentences(n))


@router.post("/samples", response_model=SampleOut, status_code=201)
def add_sample(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    store: TeachStore = Depends(get_teach_store),
    phrase: str = Form(...),
    fps: int = Form(25),
    frames: list[UploadFile] = File(...),
):
    phrase = phrase.strip()
    if not phrase:
        raise HTTPException(status_code=422, detail="phrase is required")
    blobs = [f.file.read() for f in frames]
    try:
        clip_path, n_frames = store.add_sample(user.id, phrase, blobs, fps=fps)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    sample = TrainingSample(id=uuid4().hex, user_id=user.id, phrase=phrase,
                            clip_path=clip_path, fps=fps, n_frames=n_frames)
    db.add(sample)
    db.commit()

    # Auto-retrain once enough new sentences have accumulated.
    job = enqueue_if_ready(db, user.id)
    return SampleOut(
        sample_id=sample.id, n_frames=n_frames,
        samples_total=count_samples(db, user.id),
        new_since_train=count_new_samples(db, user.id),
        training_triggered=job is not None,
        job_id=job.id if job else None,
    )


@router.get("/samples", response_model=list[SampleRow])
def list_samples(user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> list[SampleRow]:
    rows = db.scalars(
        select(TrainingSample).where(TrainingSample.user_id == user.id)
        .order_by(TrainingSample.created_at.desc())
    ).all()
    return list(rows)


@router.delete("/samples/{sample_id}", status_code=204)
def delete_sample(sample_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    s = db.get(TrainingSample, sample_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="recording not found")
    # Remove from the training store (manifest + file) so finetune won't use it,
    # then drop the DB row.
    user_training_store(user.id).delete_clip(os.path.basename(s.clip_path))
    db.delete(s)
    db.commit()
    return None


@router.get("/status", response_model=TeachStatusOut)
def status(user: User = Depends(get_current_user),
           db: Session = Depends(get_db)) -> TeachStatusOut:
    job = _latest_job(db, user.id)
    return TeachStatusOut(
        samples_total=count_samples(db, user.id),
        new_since_train=count_new_samples(db, user.id),
        retrain_threshold=RETRAIN_THRESHOLD,
        active_model_id=user.active_model_id,
        latest_job=JobOut.model_validate(job) if job else None,
    )


@router.post("/train", response_model=JobOut)
def train_now(user: User = Depends(get_current_user),
              db: Session = Depends(get_db)) -> JobOut:
    job = enqueue_if_ready(db, user.id, force=True)
    if job is None:
        # Either too few samples, or a run is already queued/running.
        existing = db.scalar(select(TrainingJob).where(
            TrainingJob.user_id == user.id,
            TrainingJob.status.in_(("queued", "running"))))
        if existing is not None:
            return JobOut.model_validate(existing)
        raise HTTPException(
            status_code=400,
            detail=f"need at least 4 recorded sentences to train "
                   f"(have {count_samples(db, user.id)}).")
    return JobOut.model_validate(job)
