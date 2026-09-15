"""Database models.

Design notes:
- Large media (audio/video clips, model checkpoints) live on disk under a
  per-user directory; the DB stores *paths + ownership + metadata*, never blobs.
  That keeps the DB small and makes the move to object storage (S3/GCS) a matter
  of swapping the storage layer, not the schema.
- Every user-owned row carries ``user_id`` so isolation is enforced in queries.
- IDs are random hex strings (uuid4) — no sequential IDs leaking counts, and
  stable across a future Postgres move.
"""

from __future__ import annotations

import time
from uuid import uuid4

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uid() -> str:
    return uuid4().hex


def _now() -> float:
    return time.time()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[float] = mapped_column(Float, default=_now)

    # The voice used for TTS and the personalized model currently in effect.
    # Nullable: a fresh user speaks with the default voice and the base model.
    default_voice_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active_model_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    voices: Mapped[list[Voice]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


class Voice(Base):
    """A cloned voice = a reference audio clip; TTS clones from it zero-shot."""

    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140))
    reference_path: Mapped[str] = mapped_column(String(1024))   # on-disk WAV
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine: Mapped[str] = mapped_column(String(32), default="voxcpm")
    created_at: Mapped[float] = mapped_column(Float, default=_now)

    user: Mapped[User] = relationship(back_populates="voices")


class TrainingSample(Base):
    """One recorded sentence: a video clip + its known phrase, for fine-tuning."""

    __tablename__ = "training_samples"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    phrase: Mapped[str] = mapped_column(Text)
    clip_path: Mapped[str] = mapped_column(String(1024))
    fps: Mapped[int] = mapped_column(Integer, default=25)
    n_frames: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=_now)
    # False until a completed training job has consumed it (drives the
    # "N new sentences since last train" auto-retrain threshold).
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class TrainingJob(Base):
    """A queued/running background fine-tune. The worker advances its status."""

    __tablename__ = "training_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    #                     queued -> running -> done | failed
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    epochs: Mapped[int] = mapped_column(Integer, default=0)
    result_model_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=_now)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class PersonalModel(Base):
    """A fine-tuned checkpoint private to one user."""

    __tablename__ = "personal_models"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    base_checkpoint: Mapped[str] = mapped_column(String(1024))
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=_now)


class PracticePhrase(Base):
    """A sentence the user flagged (e.g. a Speak misread) to record & train on."""

    __tablename__ = "practice_phrases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=_now)
