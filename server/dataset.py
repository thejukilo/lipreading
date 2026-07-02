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

        phrase = (phrase or "").strip()
        if not phrase:
            raise ValueError("Give the clip a phrase/word to teach.")
        arr = np.ascontiguousarray(frames_rgb, dtype=np.uint8)
        if arr.ndim != 4 or arr.shape[0] < MIN_FRAMES:
            raise RuntimeError(
                f"Clip too short ({0 if arr.ndim != 4 else arr.shape[0]} frames) "
                f"— record for at least ~0.3s (need {MIN_FRAMES} frames)."
            )
        os.makedirs(self.clips_dir, exist_ok=True)
        entries = self._load()
        stem = f"{_slug(phrase)}_{len(entries):04d}"
        name = self._write_clip(arr, stem, fps)
        entries.append({"clip": name, "phrase": phrase, "frames": int(arr.shape[0]),
                        "fps": fps, "created": created})
        self._save(entries)
        return self.clip_path(name)

    def _write_clip(self, arr, stem: str, fps: int) -> str:
        """Write an mp4 with OpenCV (compact, reliable); fall back to .npz.

        Avoids torchvision.io.write_video, which errors ('an integer is
        required') on newer PyAV versions.
        """
        try:
            import cv2

            t, h, w = arr.shape[:3]
            path = os.path.join(self.clips_dir, stem + ".mp4")
            vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (w, h))
            if vw.isOpened():
                for frame in arr:
                    vw.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                vw.release()
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    return stem + ".mp4"
        except Exception:
            pass
        # Fallback: lossless compressed numpy (no codec needed).
        import numpy as np

        path = os.path.join(self.clips_dir, stem + ".npz")
        np.savez_compressed(path, frames=arr, fps=fps)
        return stem + ".npz"

    def load_clip(self, name: str):
        """Load a stored clip back to RGB frames (T,H,W,3) — for fine-tuning."""
        import numpy as np

        path = self.clip_path(name)
        if name.endswith(".npz"):
            return np.load(path)["frames"]
        import cv2

        cap = cv2.VideoCapture(path)
        frames = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        cap.release()
        return np.asarray(frames, dtype=np.uint8)

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
