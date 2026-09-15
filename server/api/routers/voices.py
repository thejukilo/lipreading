"""Per-user cloned voices: upload a reference clip, list, preview, set default, delete.

A "voice" is a reference audio clip; TTS clones from it zero-shot at speak time
(no training), so "cloning" here is just securely storing the reference and
normalizing it to mono WAV. Files live under the user's private media dir; the
DB row carries ownership + metadata.
"""

# No `from __future__ import annotations`: FastAPI needs the real UploadFile/Form
# types on the signatures.

import os
import shutil
import tempfile
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User, Voice
from ..schemas import VoiceOut
from ..storage import voices_dir
from ...voices import _write_mono_wav, slugify

router = APIRouter(prefix="/api/voices", tags=["voices"])

_ENGINES = {"voxcpm", "xtts"}


def _out(v: Voice, user: User) -> VoiceOut:
    o = VoiceOut.model_validate(v)
    o.is_default = (user.default_voice_id == v.id)
    return o


@router.get("", response_model=list[VoiceOut])
def list_voices(user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> list[VoiceOut]:
    rows = db.scalars(
        select(Voice).where(Voice.user_id == user.id).order_by(Voice.created_at)
    ).all()
    return [_out(v, user) for v in rows]


@router.post("", response_model=VoiceOut, status_code=201)
def create_voice(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    name: str = Form(...),
    audio: UploadFile = File(...),
    prompt_text: str = Form(""),
    engine: str = Form("voxcpm"),
):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="voice name is required")
    if engine not in _ENGINES:
        raise HTTPException(status_code=422, detail=f"engine must be one of {sorted(_ENGINES)}")

    voice = Voice(id=uuid4().hex, user_id=user.id, name=name, slug=slugify(name),
                  reference_path="", prompt_text=prompt_text.strip() or None,
                  engine=engine)
    dest_dir = os.path.join(voices_dir(user.id), voice.id)  # keyed by id -> unique
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "reference.wav")

    # Persist the upload to a temp file, then normalize to mono WAV at dest.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix="_upload") as f:
            shutil.copyfileobj(audio.file, f)
            tmp = f.name
        try:
            _write_mono_wav(tmp, dest)
        except RuntimeError as e:  # non-WAV / unreadable audio
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)

    voice.reference_path = dest
    db.add(voice)
    # First voice becomes the default automatically.
    if not user.default_voice_id:
        user.default_voice_id = voice.id
        db.add(user)
    db.commit()
    db.refresh(voice)
    return _out(voice, user)


@router.post("/{voice_id}/default", response_model=VoiceOut)
def set_default(voice_id: str, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> VoiceOut:
    v = db.get(Voice, voice_id)
    if v is None or v.user_id != user.id:
        raise HTTPException(status_code=404, detail="voice not found")
    user.default_voice_id = v.id
    db.add(user)
    db.commit()
    return _out(v, user)


@router.get("/{voice_id}/reference")
def get_reference(voice_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    v = db.get(Voice, voice_id)
    if v is None or v.user_id != user.id or not os.path.isfile(v.reference_path):
        raise HTTPException(status_code=404, detail="voice not found")
    return FileResponse(v.reference_path, media_type="audio/wav",
                        filename=f"{v.slug}.wav")


@router.delete("/{voice_id}", status_code=204)
def delete_voice(voice_id: str, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    v = db.get(Voice, voice_id)
    if v is None or v.user_id != user.id:
        raise HTTPException(status_code=404, detail="voice not found")
    shutil.rmtree(os.path.dirname(v.reference_path), ignore_errors=True)
    was_default = user.default_voice_id == v.id
    db.delete(v)
    if was_default:
        # Fall back to another existing voice, else no default.
        other = db.scalar(
            select(Voice).where(Voice.user_id == user.id, Voice.id != v.id)
            .order_by(Voice.created_at))
        user.default_voice_id = other.id if other else None
        db.add(user)
    db.commit()
    return None
