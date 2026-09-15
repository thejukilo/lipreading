"""Per-user on-disk media layout.

    <MEDIA_DIR>/<user_id>/
        voices/<voice_slug>/reference.wav
        clips/<sample_id>.mp4          (training video clips)
        models/<model_id>.pth          (private fine-tuned checkpoints)

Keyed by the (unguessable) user id, so one user's tree is never reachable from
another's request. Swapping this module for an S3 keyed the same way is how the
cloud version stores media without touching the rest of the app.
"""

from __future__ import annotations

import os

from .config import MEDIA_DIR


def user_dir(user_id: str) -> str:
    d = os.path.join(MEDIA_DIR, user_id)
    os.makedirs(d, exist_ok=True)
    return d


def voices_dir(user_id: str) -> str:
    d = os.path.join(user_dir(user_id), "voices")
    os.makedirs(d, exist_ok=True)
    return d


def clips_dir(user_id: str) -> str:
    d = os.path.join(user_dir(user_id), "clips")
    os.makedirs(d, exist_ok=True)
    return d


def models_dir(user_id: str) -> str:
    d = os.path.join(user_dir(user_id), "models")
    os.makedirs(d, exist_ok=True)
    return d
