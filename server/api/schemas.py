"""Request/response schemas (pydantic v2)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    created_at: float
    default_voice_id: str | None = None
    active_model_id: str | None = None


class VoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    engine: str
    created_at: float
    is_default: bool = False


class SentencesOut(BaseModel):
    sentences: list[str]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    n_samples: int
    result_model_id: str | None = None
    error: str | None = None
    log: str = ""
    created_at: float
    finished_at: float | None = None


class SampleOut(BaseModel):
    sample_id: str
    n_frames: int
    samples_total: int
    new_since_train: int
    training_triggered: bool
    job_id: str | None = None


class SampleRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    phrase: str
    n_frames: int
    created_at: float
    consumed: bool


class PracticeIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class PracticePhraseOut(BaseModel):
    id: str
    text: str
    reps: int          # how many clips recorded for this phrase so far
    created_at: float


class TeachStatusOut(BaseModel):
    samples_total: int
    new_since_train: int
    retrain_threshold: int
    active_model_id: str | None = None
    latest_job: JobOut | None = None


class ModelInfoOut(BaseModel):
    active: str                       # "base" | "personal"
    has_personal: bool
    trained_at: float | None = None   # when the personal model was trained
    n_samples: int | None = None      # clips it trained on
    total_clips: int = 0              # clips recorded so far
    distinct_phrases: int = 0         # distinct sentences recorded


class ModelSelectIn(BaseModel):
    use_personal: bool
