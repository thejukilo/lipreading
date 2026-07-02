"""Text-to-speech backends for Phase 1.

Pluggable behind a tiny interface so Phase 2 voice cloning can drop in later.
Two backends:

- ``PiperTTS``  — local, fast, offline, natural. Default. Uses the piper CLI as
  a subprocess (stable across piper versions) to render a WAV file.
- ``SapiTTS``   — Windows' built-in SAPI5 via pyttsx3. Robotic but zero extra
  downloads; a fallback if piper install is painful.

Each backend renders text to a WAV file on disk; playback (into the virtual mic)
is handled separately by ``server.audio_out``.
"""

from __future__ import annotations

import os
import subprocess
import tempfile


class TTSBackend:
    def synthesize_to_wav(self, text: str, out_path: str | None = None) -> str:
        """Render ``text`` to a WAV file and return its path."""
        raise NotImplementedError


def _tmp_wav() -> str:
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="tts_")
    os.close(fd)
    return path


class PiperTTS(TTSBackend):
    """Local neural TTS via the piper CLI.

    Parameters
    ----------
    model_path:
        Path to a piper voice ``.onnx`` (its ``.onnx.json`` config must sit
        next to it). Falls back to ``$PIPER_MODEL`` then a default location.
    piper_bin:
        The piper executable (default ``$PIPER_BIN`` or ``"piper"`` on PATH).
    """

    def __init__(self, model_path: str | None = None, piper_bin: str | None = None) -> None:
        self.model_path = os.path.abspath(
            model_path
            or os.environ.get("PIPER_MODEL", "models/piper/en_US-lessac-medium.onnx")
        )
        self.piper_bin = piper_bin or os.environ.get("PIPER_BIN", "piper")
        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(
                f"Piper voice model not found: {self.model_path}\n"
                "Run the setup script to download it, or set PIPER_MODEL."
            )

    def synthesize_to_wav(self, text: str, out_path: str | None = None) -> str:
        out_path = out_path or _tmp_wav()
        try:
            proc = subprocess.run(
                [self.piper_bin, "--model", self.model_path, "--output_file", out_path],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"piper executable '{self.piper_bin}' not found. Install piper-tts "
                "(pip install piper-tts) or set PIPER_BIN / use --tts sapi."
            ) from e
        if proc.returncode != 0 or not os.path.isfile(out_path):
            raise RuntimeError(
                "piper failed:\n" + proc.stderr.decode("utf-8", "ignore")
            )
        return out_path


class SapiTTS(TTSBackend):
    """Windows SAPI5 via pyttsx3 — no model download, robotic but always there."""

    def __init__(self, rate: int | None = None, voice: str | None = None) -> None:
        try:
            import pyttsx3  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "pyttsx3 not installed (pip install pyttsx3) — needed for --tts sapi."
            ) from e
        self._rate = rate
        self._voice = voice

    def synthesize_to_wav(self, text: str, out_path: str | None = None) -> str:
        import pyttsx3

        out_path = out_path or _tmp_wav()
        # A fresh engine per call avoids pyttsx3's run-loop reuse quirks.
        engine = pyttsx3.init()
        if self._rate is not None:
            engine.setProperty("rate", self._rate)
        if self._voice is not None:
            engine.setProperty("voice", self._voice)
        engine.save_to_file(text, out_path)  # writes file, does NOT hit speakers
        engine.runAndWait()
        engine.stop()
        if not os.path.isfile(out_path):
            raise RuntimeError("pyttsx3 did not produce a WAV file.")
        return out_path


class XttsTTS(TTSBackend):
    """Zero-shot voice cloning via Coqui XTTS v2.

    Clones the voice in ``speaker_wav`` (a short reference clip) — no training.
    The (large) model is cached at class level and loaded on first use, so
    switching between cloned voices is cheap and Piper users never pay for it.

    Note: the XTTS v2 model license (CPML) is non-commercial.
    """

    _model = None  # shared across instances

    def __init__(self, speaker_wav: str, language: str = "en") -> None:
        if not os.path.isfile(speaker_wav):
            raise FileNotFoundError(f"Voice reference audio not found: {speaker_wav}")
        self.speaker_wav = speaker_wav
        self.language = language

    @classmethod
    def _get_model(cls):
        if cls._model is None:
            # Accept the non-commercial model license non-interactively so the
            # GUI doesn't hang on a stdin prompt. (Documented for the user.)
            os.environ.setdefault("COQUI_TOS_AGREED", "1")
            try:
                from TTS.api import TTS
            except Exception as e:
                import sys

                raise RuntimeError(
                    "Voice cloning couldn't load coqui-tts (the 'TTS' package).\n"
                    f"Underlying error: {type(e).__name__}: {e}\n"
                    f"App is running this Python:\n  {sys.executable}\n"
                    "Most common cause: coqui-tts is installed in a DIFFERENT "
                    "environment. Install it into the one above:\n"
                    f'  "{sys.executable}" -m pip install coqui-tts\n'
                    "(first synthesis also downloads the ~1.8GB XTTS v2 model)."
                ) from e
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            cls._model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        return cls._model

    def synthesize_to_wav(self, text: str, out_path: str | None = None) -> str:
        out_path = out_path or _tmp_wav()
        model = self._get_model()
        model.tts_to_file(
            text=text,
            speaker_wav=self.speaker_wav,
            language=self.language,
            file_path=out_path,
        )
        return out_path


def make_tts(backend: str = "piper", **kwargs) -> TTSBackend:
    backend = backend.lower()
    if backend == "piper":
        return PiperTTS(**kwargs)
    if backend == "sapi":
        return SapiTTS(**kwargs)
    if backend == "xtts":
        return XttsTTS(**kwargs)
    raise ValueError(f"Unknown TTS backend: {backend!r} (use 'piper', 'sapi', 'xtts').")


def make_tts_for_voice(voice_id: str, store=None) -> TTSBackend:
    """Resolve a voice id to a TTS backend.

    Voice ids: ``"piper"``, ``"sapi"``, or ``"clone:<slug>"`` (a cloned voice
    from the VoicesStore).
    """
    if voice_id in ("piper", "sapi"):
        return make_tts(voice_id)
    if voice_id.startswith("clone:"):
        from .voices import VoicesStore

        store = store or VoicesStore()
        slug = voice_id.split(":", 1)[1]
        return XttsTTS(speaker_wav=store.get_reference(slug))
    # Unknown/stale selection -> safe default.
    return make_tts("piper")
