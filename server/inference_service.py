"""Shared, headless inference service for the web API.

Holds the heavy model (VSR engine), the TTS voice and the optional LLM cleanup —
loaded once and reused across HTTP requests. The GPU model isn't reentrant, so
every model call is serialized behind a lock; concurrent phone requests queue.

It deliberately reuses the *same* builders the desktop app uses
(``LipreadingEngine``, ``make_tts_for_voice``, ``make_corrector``) and the same
saved config, so a phone gets identical behaviour to the local Speak tab.
"""

from __future__ import annotations

import os
import threading


class InferenceService:
    def __init__(self, cfg=None) -> None:
        if cfg is None:
            from .settings import load_config

            cfg = load_config()
        self.cfg = cfg
        self._lock = threading.Lock()      # serialize model use (single GPU model)
        self._load_lock = threading.Lock()
        self.engine = None
        self.tts = None
        self.corrector = None
        self.loaded = False
        self.load_error: str | None = None

    # ---- lifecycle --------------------------------------------------------

    def load(self) -> None:
        """Build engine + TTS + corrector. Idempotent; safe to call repeatedly."""
        with self._load_lock:
            if self.loaded:
                return
            from .corrector import make_corrector
            from .engine import LipreadingEngine
            from .tts import make_tts_for_voice

            device = self.cfg.device or ("cuda:0" if _cuda() else "cpu")
            self.engine = LipreadingEngine(
                checkpoint_path=self.cfg.checkpoint,
                auto_avsr_dir=self.cfg.auto_avsr_dir,
                detector=self.cfg.detector,
                device=device,
            )
            self.tts = make_tts_for_voice(
                self.cfg.voice, clone_engine=self.cfg.clone_engine,
                clone_timesteps=self.cfg.clone_timesteps,
            )
            try:
                self.tts.warmup()
            except Exception:
                pass  # warmup is best-effort; first synth will surface real errors
            self.corrector = make_corrector(
                self.cfg.corrector, model=self.cfg.corrector_model,
                api_key=self.cfg.corrector_api_key,
                ollama_host=self.cfg.corrector_ollama_host,
                context=self.cfg.corrector_context,
            )
            self.loaded = True

    # ---- inference --------------------------------------------------------

    def transcribe(self, frames_rgb, cleanup: bool = True) -> str:
        """Frames (T,H,W,3 RGB uint8, ~25 fps) -> cleaned transcript text."""
        if not self.loaded:
            self.load()
        with self._lock:
            text = self.engine.transcribe_frames(frames_rgb)
        text = (text or "").strip()
        if cleanup and text and self.corrector is not None:
            from .corrector import NoopCorrector

            if not isinstance(self.corrector, NoopCorrector):
                try:
                    text = (self.corrector.correct(text) or text).strip()
                except Exception:
                    pass  # cleanup is optional — fall back to the raw transcript
        return text

    def synthesize_wav(self, text: str) -> bytes:
        """Text -> WAV bytes (the phone plays these)."""
        if not self.loaded:
            self.load()
        with self._lock:
            path = self.tts.synthesize_to_wav(text)
        try:
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def _cuda() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def decode_jpeg_frames(blobs, max_side: int | None = None):
    """Decode a list of JPEG byte-strings into a (T,H,W,3) RGB uint8 array.

    The mobile client grabs webcam frames off a canvas and posts them as JPEGs
    (codec-independent — no MediaRecorder/webm/mp4 decoding needed, so it behaves
    the same on iOS and Android). Undecodable frames are skipped.
    """
    import cv2
    import numpy as np

    frames = []
    for b in blobs:
        arr = np.frombuffer(b, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR
        if img is None:
            continue
        if max_side:
            h, w = img.shape[:2]
            scale = max_side / float(max(h, w))
            if scale < 1.0:
                img = cv2.resize(img, (int(w * scale), int(h * scale)),
                                 interpolation=cv2.INTER_AREA)
        frames.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if not frames:
        return np.empty((0,), dtype=np.uint8)
    return np.ascontiguousarray(np.stack(frames), dtype=np.uint8)
