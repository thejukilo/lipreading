"""On-disk store for personalized training clips (the Teaching tab).

Each item is a short webcam clip labeled with the word/sentence the user said,
stored so a later fine-tuning step can reprocess it through the same mouth-crop
pipeline as inference. Clips live in ``~/.lipreading/training/`` as 25 fps mp4s
with a manifest.
"""

from __future__ import annotations

import json
import os
import re

TRAINING_DIR = os.path.join(os.path.expanduser("~"), ".lipreading", "training")

MIN_FRAMES = 8  # ~0.3s at 25 fps — anything shorter isn't usable


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    return s or "clip"


class TrainingStore:
    def __init__(self, base_dir: str = TRAINING_DIR) -> None:
        self.base_dir = base_dir
        self.clips_dir = os.path.join(base_dir, "clips")
        self.manifest_path = os.path.join(base_dir, "manifest.json")

    # ---- manifest ---------------------------------------------------------

    def _load(self) -> list[dict]:
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, entries: list[dict]) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)

    # ---- add / list / delete ---------------------------------------------

    def add_clip(self, phrase: str, frames_rgb, fps: int = 25,
                 created: float | None = None) -> str:
        """Save an RGB frame sequence (T,H,W,3 uint8) as a labeled clip."""
        import numpy as np
        import torch
        import torchvision

        phrase = (phrase or "").strip()
        if not phrase:
            raise ValueError("Give the clip a phrase/word to teach.")
        arr = np.asarray(frames_rgb, dtype=np.uint8)
        if arr.ndim != 4 or arr.shape[0] < MIN_FRAMES:
            raise RuntimeError(
                f"Clip too short ({0 if arr.ndim != 4 else arr.shape[0]} frames) "
                f"— record for at least ~0.3s (need {MIN_FRAMES} frames)."
            )
        os.makedirs(self.clips_dir, exist_ok=True)
        entries = self._load()
        idx = len(entries)
        name = f"{_slug(phrase)}_{idx:04d}.mp4"
        path = os.path.join(self.clips_dir, name)
        # torchvision.io.write_video wants a uint8 tensor of shape (T, H, W, C).
        torchvision.io.write_video(path, torch.from_numpy(arr), fps)
        entries.append({"clip": name, "phrase": phrase, "frames": int(arr.shape[0]),
                        "created": created})
        self._save(entries)
        return path

    def items_grouped(self) -> list[dict]:
        """[{phrase, count, clips:[name,...]}, ...] sorted by phrase."""
        groups: dict[str, dict] = {}
        for e in self._load():
            g = groups.setdefault(e["phrase"], {"phrase": e["phrase"], "count": 0, "clips": []})
            g["count"] += 1
            g["clips"].append(e["clip"])
        return sorted(groups.values(), key=lambda g: g["phrase"].lower())

    def stats(self) -> tuple[int, int]:
        entries = self._load()
        return len(entries), len({e["phrase"] for e in entries})

    def clip_path(self, name: str) -> str:
        return os.path.join(self.clips_dir, name)

    def delete_phrase(self, phrase: str) -> None:
        keep = []
        for e in self._load():
            if e["phrase"] == phrase:
                try:
                    os.remove(self.clip_path(e["clip"]))
                except OSError:
                    pass
            else:
                keep.append(e)
        self._save(keep)
