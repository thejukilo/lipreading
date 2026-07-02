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


def make_tts(backend: str = "piper", **kwargs) -> TTSBackend:
    backend = backend.lower()
    if backend == "piper":
        return PiperTTS(**kwargs)
    if backend == "sapi":
        return SapiTTS(**kwargs)
    raise ValueError(f"Unknown TTS backend: {backend!r} (use 'piper' or 'sapi').")
