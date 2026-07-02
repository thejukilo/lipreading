"""Cloned-voice store.

A "voice" is just a reference audio clip the user recorded or uploaded; XTTS
clones from it at synthesis time (zero-shot, no training). Each voice lives in
``~/.lipreading/voices/<slug>/`` with ``reference.wav`` + ``meta.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time

VOICES_DIR = os.path.join(os.path.expanduser("~"), ".lipreading", "voices")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return slug or "voice"


class VoicesStore:
    def __init__(self, base_dir: str = VOICES_DIR) -> None:
        self.base_dir = base_dir

    def _dir(self, slug: str) -> str:
        return os.path.join(self.base_dir, slug)

    def reference_path(self, slug: str) -> str:
        return os.path.join(self._dir(slug), "reference.wav")

    def exists(self, slug: str) -> bool:
        return os.path.isfile(self.reference_path(slug))

    def list_voices(self) -> list[dict]:
        """Return [{slug, name, created}, ...] sorted by name."""
        out = []
        if not os.path.isdir(self.base_dir):
            return out
        for slug in os.listdir(self.base_dir):
            if not self.exists(slug):
                continue
            meta = self._read_meta(slug)
            out.append({"slug": slug, "name": meta.get("name", slug),
                        "created": meta.get("created")})
        return sorted(out, key=lambda v: v["name"].lower())

    def _read_meta(self, slug: str) -> dict:
        try:
            with open(os.path.join(self._dir(slug), "meta.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def get_reference(self, slug: str) -> str:
        path = self.reference_path(slug)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Voice '{slug}' has no reference audio.")
        return path

    def add_from_wav(
        self,
        name: str,
        src_wav: str,
        created: float | None = None,
        prompt_text: str | None = None,
    ) -> str:
        """Store a voice from an existing WAV file. Returns the slug.

        The source is normalized to mono WAV. ``prompt_text`` is the transcript
        of the reference clip (known when the user reads our recording passage);
        VoxCPM uses it for higher-quality cloning. ``created`` is a unix
        timestamp (passed in so this module needs no clock and stays testable).
        """
        slug = slugify(name)
        d = self._dir(slug)
        os.makedirs(d, exist_ok=True)
        _write_mono_wav(src_wav, self.reference_path(slug))
        meta = {"name": name.strip() or slug, "slug": slug, "created": created,
                "source": os.path.basename(src_wav), "prompt_text": prompt_text}
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return slug

    def get_prompt_text(self, slug: str) -> str | None:
        return self._read_meta(slug).get("prompt_text")

    def delete(self, slug: str) -> None:
        shutil.rmtree(self._dir(slug), ignore_errors=True)


def _write_mono_wav(src: str, dst: str) -> None:
    """Read ``src`` (WAV), downmix to mono, write to ``dst``.

    WAV in / WAV out keeps deps minimal. Non-WAV uploads (mp3/m4a) aren't decoded
    here — we surface a clear error asking for a WAV (or a recording).
    """
    import numpy as np
    import soundfile as sf

    try:
        data, sr = sf.read(src, dtype="float32", always_2d=True)
    except Exception as e:
        raise RuntimeError(
            f"Could not read '{os.path.basename(src)}'. Please provide a WAV file "
            "(or record directly in the app)."
        ) from e
    mono = data.mean(axis=1)
    if dst != src:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    sf.write(dst, mono, sr, subtype="PCM_16")
