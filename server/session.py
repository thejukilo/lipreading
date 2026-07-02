"""Headless live-session controller.

All the capture -> transcribe -> speak logic, with **no UI toolkit**: the CLI
(OpenCV) and the desktop GUI (PySide6) both drive this same object and read its
state, so behavior stays identical across front-ends.

Threading model (unchanged from the validated CLI):
- a capture thread grabs webcam frames, samples them to 25 fps, and appends to
  the utterance buffer while ``recording`` is set;
- ``stop_recording()`` hands the buffer to a transcription worker thread;
- speaking (TTS + playback) runs in its own worker thread.

Front-ends poll the public attributes (``state``, ``latest_bgr``,
``frame_count``, ``pending_text``, ``monitor_on``, ``last_status``) and/or set the
optional ``on_status`` / ``on_state`` callbacks.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field


@dataclass
class SessionConfig:
    checkpoint: str = os.environ.get("VSR_CHECKPOINT", "checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth")
    auto_avsr_dir: str | None = None
    detector: str = "mediapipe"
    device: str | None = None          # None -> auto (cuda if available)
    camera: int = 0
    width: int = 640
    height: int = 480
    tts: str = "piper"                 # built-in engine (CLI --tts); see `voice`
    voice: str = "piper"               # selector: "piper" | "sapi" | "clone:<slug>"
    output_device: str | int | None = "CABLE Input"   # the virtual mic
    monitor_device: str | int | None = None            # None -> default speakers
    monitor_on: bool = True
    auto_speak: bool = False
    ptt_key: str = "ctrl_r"            # used by front-ends, not the session itself


class LiveSession:
    IDLE, RECORDING, BUSY, REVIEW, SPEAKING = "idle", "recording", "busy", "review", "speaking"
    MIN_FRAMES = 8

    def __init__(self, cfg: SessionConfig) -> None:
        self.cfg = cfg
        self.state = self.IDLE
        self.recording = False
        self.monitor_on = cfg.monitor_on

        self.utterance = []
        self.latest_bgr = None
        self.pending_text = ""
        self.last_status = ""

        self._buf_lock = threading.Lock()
        self._running = False
        self._cap_thread = None

        self.engine = None
        self.tts = None
        self.cap = None
        self.out_device = None

        # Optional UI hooks (called from worker threads — marshal to UI yourself).
        self.on_status = None
        self.on_state = None

    # ---- lifecycle --------------------------------------------------------

    def load(self) -> None:
        """Build the (heavy) model + TTS. Call once, off the UI thread."""
        from .engine import LipreadingEngine

        self._set_status(f"loading model ({os.path.basename(self.cfg.checkpoint)})…")
        self.engine = LipreadingEngine(
            checkpoint_path=self.cfg.checkpoint,
            auto_avsr_dir=self.cfg.auto_avsr_dir,
            detector=self.cfg.detector,
            device=self._resolve_device(),
        )
        self.reconfigure_audio()
        self._set_status("ready")

    def reconfigure_audio(self) -> None:
        """(Re)build the cheap audio bits from cfg — TTS engine, output, monitor."""
        from .audio_out import resolve_output_device
        from .tts import make_tts_for_voice

        self.tts = make_tts_for_voice(self.cfg.voice)
        self.out_device = resolve_output_device(self.cfg.output_device)
        self.monitor_on = self.cfg.monitor_on

    @property
    def is_loaded(self) -> bool:
        return self.engine is not None

    @property
    def is_running(self) -> bool:
        return self._running

    def _resolve_device(self) -> str:
        if self.cfg.device:
            return self.cfg.device
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"

    def start(self) -> None:
        """Open the camera and start the capture thread."""
        import cv2

        if self._running:
            return
        cam_api = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0
        self.cap = cv2.VideoCapture(self.cfg.camera, cam_api)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera index {self.cfg.camera}.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
        self.cap.set(cv2.CAP_PROP_FPS, 25)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        self._running = True
        self._cap_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._cap_thread.start()

    def stop(self) -> None:
        """Stop capture and release the camera (keeps the model loaded)."""
        self._running = False
        self.recording = False
        if self._cap_thread is not None:
            self._cap_thread.join(timeout=1.0)
            self._cap_thread = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self._set_state(self.IDLE)

    def shutdown(self) -> None:
        self.stop()

    # ---- capture ----------------------------------------------------------

    def _capture_loop(self) -> None:
        import cv2

        period = 1.0 / 25.0
        next_keep = time.monotonic()
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.005)
                continue
            self.latest_bgr = frame
            now = time.monotonic()
            if now >= next_keep:
                next_keep = max(next_keep + period, now - period)
                if self.recording:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    with self._buf_lock:
                        self.utterance.append(rgb)

    @property
    def frame_count(self) -> int:
        with self._buf_lock:
            return len(self.utterance)

    # ---- push-to-talk -----------------------------------------------------

    def start_recording(self) -> None:
        if self.state != self.IDLE:
            return
        with self._buf_lock:
            self.utterance = []
        self.recording = True
        self._set_state(self.RECORDING)

    def stop_recording(self) -> None:
        self.recording = False
        if self.state != self.RECORDING:
            return
        with self._buf_lock:
            frames = self.utterance
            self.utterance = []
        self._set_state(self.BUSY)
        threading.Thread(target=self._transcribe_worker, args=(frames,), daemon=True).start()

    # ---- workers ----------------------------------------------------------

    def _transcribe_worker(self, frames) -> None:
        import numpy as np

        try:
            arr = np.asarray(frames, dtype=np.uint8)
            t0 = time.perf_counter()
            text = self.engine.transcribe_frames(arr)
            dt = time.perf_counter() - t0
        except Exception as e:
            self._set_status(f"! {e}")
            self._set_state(self.IDLE)
            return

        text = (text or "").strip()
        if not text:
            self._set_status("! empty transcript — try again")
            self._set_state(self.IDLE)
            return
        self._set_status(f"transcript ({len(frames)} frames, {dt:.1f}s)")

        if self.cfg.auto_speak:
            self.speak(text)
        else:
            self.pending_text = text
            self._set_state(self.REVIEW)

    def speak(self, text: str) -> None:
        """Synthesize ``text`` and play it into the virtual mic (+ monitor)."""
        text = (text or "").strip()
        if not text:
            self._set_state(self.IDLE)
            return
        self.pending_text = ""
        self._set_state(self.SPEAKING)
        threading.Thread(target=self._speak_worker, args=(text,), daemon=True).start()

    def _speak_worker(self, text: str) -> None:
        from .audio_out import play_wav

        try:
            wav = self.tts.synthesize_to_wav(text)
            play_wav(
                wav,
                device=self.out_device,
                monitor=self.monitor_on,
                monitor_device=self.cfg.monitor_device,
                blocking=True,
            )
            try:
                os.remove(wav)
            except OSError:
                pass
        except Exception as e:
            self._set_status(f"! TTS/playback failed: {e}")
        finally:
            self._set_state(self.IDLE)

    def discard(self) -> None:
        self.pending_text = ""
        self._set_status("discarded")
        self._set_state(self.IDLE)

    # ---- monitor ----------------------------------------------------------

    def set_monitor(self, on: bool) -> None:
        self.monitor_on = on
        self._set_status(f"monitor {'ON' if on else 'OFF'}")

    def toggle_monitor(self) -> None:
        self.set_monitor(not self.monitor_on)

    # ---- helpers ----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self.state = state
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                pass

    def _set_status(self, msg: str) -> None:
        self.last_status = msg
        print(f"[session] {msg}")
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass
