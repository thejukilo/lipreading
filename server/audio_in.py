"""Microphone recording for the voice-cloning wizard (start/stop)."""

from __future__ import annotations

import threading


class Recorder:
    """Record from an input device until stopped; save as mono WAV.

    Usage:
        r = Recorder(); r.start(); ...; r.stop(); r.save("ref.wav")
    ``seconds`` (read while recording) drives the UI progress/countdown.
    """

    def __init__(self, samplerate: int = 22050, device: int | None = None) -> None:
        self.samplerate = samplerate
        self.device = device
        self._blocks = []
        self._lock = threading.Lock()
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        self._blocks = []

        def cb(indata, frames, time_info, status):  # noqa: ARG001
            with self._lock:
                self._blocks.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.samplerate, channels=1, dtype="float32", callback=cb
        )
        self._stream.start()

    @property
    def seconds(self) -> float:
        with self._lock:
            n = sum(len(b) for b in self._blocks)
        return n / float(self.samplerate)

    def stop(self):
        import numpy as np

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            if not self._blocks:
                return np.zeros((0,), dtype="float32")
            return np.concatenate(self._blocks, axis=0).reshape(-1)

    def save(self, path: str, data=None) -> str:
        import soundfile as sf

        if data is None:
            data = self.stop()
        sf.write(path, data, self.samplerate, subtype="PCM_16")
        return path
