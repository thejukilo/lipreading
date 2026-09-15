"""The core speak loop: POST /api/utter.

A push-to-talk clip (JPEG frames) -> the user's transcript -> (optionally) their
cloned voice as WAV. Uses the caller's private model + default voice when set,
otherwise the shared base model + default voice.
"""

# No `from __future__ import annotations`: FastAPI must see the real
# UploadFile/Form types on the signature, not stringized forward refs.

import base64
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import PersonalModel, User, Voice
from ..speech import SpeechError, SpeechService, TooFewFrames, get_speech_service

router = APIRouter(prefix="/api", tags=["speak"])


def _resolve_model_path(db: Session, user: User):
    """The user's active private checkpoint, if it exists on disk; else None (base)."""
    if user.active_model_id:
        pm = db.get(PersonalModel, user.active_model_id)
        if pm is not None and pm.user_id == user.id and os.path.isfile(pm.path):
            return pm.path
    return None


def _resolve_voice(db: Session, user: User):
    """(reference_path, prompt_text, engine) for the user's default voice, else default."""
    if user.default_voice_id:
        v = db.get(Voice, user.default_voice_id)
        if v is not None and v.user_id == user.id and os.path.isfile(v.reference_path):
            return v.reference_path, v.prompt_text, v.engine
    return None, None, "voxcpm"


@router.post("/utter")
async def utter(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: SpeechService = Depends(get_speech_service),
    frames: list[UploadFile] = File(...),
    fps: int = Form(25),
    speak: bool = Form(True),
    cleanup: bool = Form(True),
):
    # async endpoint on purpose: the model was imported+built on the main
    # (event-loop) thread at startup, so we run inference here on that same
    # thread rather than a threadpool worker (native heap-safe on Windows).
    blobs = [await f.read() for f in frames]
    model_path = _resolve_model_path(db, user)
    try:
        text = service.transcribe(blobs, fps=fps, cleanup=cleanup, model_path=model_path)
    except TooFewFrames as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SpeechError as e:
        raise HTTPException(status_code=500, detail=f"transcription failed: {e}")

    if not text:
        return {"text": "", "audio": None, "message": "empty transcript — try again"}

    audio_b64 = None
    if speak:
        voice_ref, prompt_text, engine = _resolve_voice(db, user)
        try:
            wav = service.synthesize_wav(text, voice_ref=voice_ref,
                                         prompt_text=prompt_text, engine=engine)
            audio_b64 = base64.b64encode(wav).decode("ascii")
        except Exception as e:  # noqa: BLE001 - text still succeeded; report voice failure
            return {"text": text, "audio": None, "message": f"voice failed: {e}"}

    return {"text": text, "audio": audio_b64, "audio_mime": "audio/wav"}
