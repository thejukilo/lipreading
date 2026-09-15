"""Per-user speech: lips -> text (their private model) and text -> their voice.

The heavy ML (VSR engine, TTS, LLM cleanup) lives in the existing modules; this
wraps them with **per-user selection**:

- transcription uses the user's active private checkpoint when they have one,
  else the shared base model;
- synthesis uses the user's chosen cloned voice when they have one, else the
  configured default voice.

Everything heavy is imported lazily and guarded by a lock (one GPU, not
reentrant), so importing this module is cheap and the router stays unit-testable
with a fake service (see tests). The router resolves per-user paths from the DB
and passes them in, keeping this layer database-agnostic.
"""

from __future__ import annotations

import os
import threading

MIN_FRAMES = 8   # ~0.3s at 25fps; anything shorter isn't readable


class SpeechError(Exception):
    """A speech operation failed (model/voice error)."""


class TooFewFrames(SpeechError):
    """The uploaded clip had too few usable frames to read."""


class SpeechService:
    """Interface the API depends on (overridden with a fake in tests)."""

    def transcribe(self, frame_blobs: list[bytes], fps: int = 25,
                   cleanup: bool = True, model_path: str | None = None) -> str:
        raise NotImplementedError

    def synthesize_wav(self, text: str, voice_ref: str | None = None,
                       prompt_text: str | None = None, engine: str = "voxcpm") -> bytes:
        raise NotImplementedError


class LocalSpeechService(SpeechService):
    """Runs the real models on this machine.

    Engines are cached by checkpoint path (base + a couple of personal models);
    TTS backends are cached by voice. A single lock serializes all GPU use.
    """

    def __init__(self, cfg=None) -> None:
        if cfg is None:
            from ..settings import load_config

            cfg = load_config()
        from .config import BASE_CHECKPOINT

        self.cfg = cfg
        # Pin the base model to the API's own choice, NOT whatever the desktop
        # app last saved in ~/.lipreading/config.json (which may be the Dutch
        # model). Per-user private models still override this per request.
        self.cfg.checkpoint = BASE_CHECKPOINT
        # Serializes GPU use between request inference and the training worker.
        self._lock = threading.Lock()
        self._engines: dict[str, object] = {}      # checkpoint path -> engine
        self._tts_cache: dict[tuple, object] = {}   # voice key -> TTS backend
        self._corrector = None
        self._corrector_ready = False

    def preload(self) -> None:
        """Import heavy deps + build the base engine ON THE CALLING THREAD.

        Must run on the *main* thread at startup: on Windows some native
        extensions (pyarrow, pulled in via transformers) corrupt the process
        heap (0xc0000374) when first imported on a worker thread. Doing the
        imports here, on the main thread, means every later use just reuses the
        already-loaded modules — including the background training worker.
        """
        self._engine(self.cfg.checkpoint)
        self._get_corrector()
        try:
            self._tts_for(None, None, self.cfg.clone_engine)  # default voice
        except Exception:
            pass  # a missing default voice model shouldn't block startup

    # ---- engines ----------------------------------------------------------

    def _engine(self, model_path: str | None):
        path = model_path or self.cfg.checkpoint
        eng = self._engines.get(path)
        if eng is None:
            from ..engine import LipreadingEngine

            device = self.cfg.device or ("cuda:0" if _cuda() else "cpu")
            eng = LipreadingEngine(
                checkpoint_path=path, auto_avsr_dir=self.cfg.auto_avsr_dir,
                detector=self.cfg.detector, device=device)
            # Bounded cache: always keep the base engine; evict an old personal
            # one when we exceed a small budget (few concurrent users locally).
            if len(self._engines) >= 3:
                for k in list(self._engines):
                    if k != self.cfg.checkpoint:
                        self._engines.pop(k, None)
                        break
            self._engines[path] = eng
        return eng

    def _get_corrector(self):
        if not self._corrector_ready:
            from ..corrector import make_corrector

            self._corrector = make_corrector(
                self.cfg.corrector, model=self.cfg.corrector_model,
                api_key=self.cfg.corrector_api_key,
                ollama_host=self.cfg.corrector_ollama_host,
                context=self.cfg.corrector_context)
            self._corrector_ready = True
        return self._corrector

    # ---- inference --------------------------------------------------------

    def transcribe(self, frame_blobs, fps=25, cleanup=True, model_path=None) -> str:
        from ..inference_service import decode_jpeg_frames

        arr = decode_jpeg_frames(frame_blobs, max_side=480)
        if arr.shape[0] < MIN_FRAMES:
            raise TooFewFrames(
                f"only {int(arr.shape[0])} usable frame(s) — hold the button longer.")
        try:
            with self._lock:
                eng = self._engine(model_path)
                text = eng.transcribe_frames(arr)
        except Exception as e:  # noqa: BLE001 - surface as a clean service error
            raise SpeechError(str(e)) from e
        text = (text or "").strip()
        if cleanup and text:
            from ..corrector import NoopCorrector

            corr = self._get_corrector()
            if corr is not None and not isinstance(corr, NoopCorrector):
                try:
                    text = (corr.correct(text) or text).strip()
                except Exception:
                    pass  # cleanup is best-effort
        return text

    def synthesize_wav(self, text, voice_ref=None, prompt_text=None, engine="voxcpm") -> bytes:
        try:
            with self._lock:
                path = self._tts_for(voice_ref, prompt_text, engine).synthesize_to_wav(text)
        except Exception as e:  # noqa: BLE001
            raise SpeechError(str(e)) from e
        try:
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _tts_for(self, voice_ref, prompt_text, engine):
        key = (voice_ref or f"default:{self.cfg.voice}", engine, prompt_text or "")
        tts = self._tts_cache.get(key)
        if tts is None:
            from ..tts import VoxCpmTTS, XttsTTS, make_tts_for_voice

            if voice_ref:
                if engine == "xtts":
                    tts = XttsTTS(speaker_wav=voice_ref)
                else:
                    tts = VoxCpmTTS(reference_wav=voice_ref,
                                    prompt_text=prompt_text or None,
                                    inference_timesteps=self.cfg.clone_timesteps)
            else:
                tts = make_tts_for_voice(
                    self.cfg.voice, clone_engine=self.cfg.clone_engine,
                    clone_timesteps=self.cfg.clone_timesteps)
            self._tts_cache[key] = tts
        return tts


def _cuda() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


# ---- singleton dependency -------------------------------------------------

_service: SpeechService | None = None
_service_lock = threading.Lock()


def get_speech_service() -> SpeechService:
    """FastAPI dependency: the process-wide speech service (built once)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = LocalSpeechService()
    return _service
