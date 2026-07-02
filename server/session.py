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
    clone_engine: str = "voxcpm"       # cloned-voice engine: "voxcpm" | "xtts"
    clone_timesteps: int = 10          # VoxCPM inference steps; lower = faster, rougher
    output_device: str | int | None = "CABLE Input"   # the virtual mic
    monitor_device: str | int | None = None            # None -> default speakers
    monitor_on: bool = True
    auto_speak: bool = False
    ptt_key: str = "ctrl_r"            # used by front-ends, not the session itself
    # LLM transcript cleanup (fixes lipreading homophone errors)
    corrector: str = "off"            # "off" | "ollama" | "anthropic"
    corrector_model: str = ""         # backend default if empty
    corrector_api_key: str = ""       # Claude backend; else uses $ANTHROPIC_API_KEY
    corrector_ollama_host: str = "http://localhost:11434"
    corrector_context: str = ""       # names/jargon to bias the cleanup (e.g. "Juan")


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
        self.last_frames = None      # frames of the last transcribed utterance
        self.pending_text = ""
        self.last_status = ""

        self._buf_lock = threading.Lock()
        self._running = False
        self._cap_thread = None
        self._open_event = threading.Event()
        self._open_error = None

        self.engine = None
        self.tts = None
        self.corrector = None
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
        from .corrector import make_corrector
        from .tts import make_tts_for_voice

        self.tts = make_tts_for_voice(
            self.cfg.voice, clone_engine=self.cfg.clone_engine,
            clone_timesteps=self.cfg.clone_timesteps,
        )
        self.corrector = make_corrector(
            self.cfg.corrector, model=self.cfg.corrector_model,
            api_key=self.cfg.corrector_api_key, ollama_host=self.cfg.corrector_ollama_host,
            context=self.cfg.corrector_context,
        )
        self.out_device = resolve_output_device(self.cfg.output_device)
        self.monitor_on = self.cfg.monitor_on

        # Preload the (heavy) neural voice model now, during Start, so the first
        # play isn't slow. Failures here shouldn't block Start — they'll surface
        # clearly at synth time instead.
        try:
            self._set_status("warming up voice…")
            self.tts.warmup()
            self._set_status("ready")
        except Exception as e:
            self._set_status(f"voice warmup deferred: {e}")

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
        """Start the capture thread (which opens the camera) and wait for it.

        The camera is opened *and* read on the one capture thread — opening on
        one thread and reading on another can hard-crash OpenCV on Windows.
        """
        if self._running:
            return
        self._open_error = None
        self._open_event = threading.Event()
        self._running = True
        self._cap_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._cap_thread.start()
        self._open_event.wait(timeout=15)  # wait for the camera to open (or fail)
        if self._open_error:
            self._running = False
            raise RuntimeError(self._open_error)
        if not self._open_event.is_set():
            self._running = False
            raise RuntimeError("Camera did not start in time — try again or pick another camera.")

    def stop(self) -> None:
        """Stop capture (the thread releases the camera). Keeps the model loaded."""
        self._running = False
        self.recording = False
        if self._cap_thread is not None:
            self._cap_thread.join(timeout=3.0)
            self._cap_thread = None
        self.cap = None
        self.latest_bgr = None
        self._set_state(self.IDLE)

    def shutdown(self) -> None:
        self.stop()

    # ---- capture ----------------------------------------------------------

    def _capture_loop(self) -> None:
        import cv2

        from .devices import open_camera

        cap, backend = open_camera(self.cfg.camera, self.cfg.width, self.cfg.height)
        if cap is None:
            self._open_error = (
                f"Could not open camera {self.cfg.camera}. Close other apps using "
                "the webcam (e.g. Google Meet), or pick a different camera and "
                "press Refresh devices."
            )
            self._running = False
            self._open_event.set()
            return
        self.cap = cap
        self._set_status(f"camera {self.cfg.camera} open ({backend})")
        self._open_event.set()

        period = 1.0 / 25.0
        next_keep = time.monotonic()
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
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
        finally:
            cap.release()

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

    # ---- clip capture for the Teaching tab (no transcription) -------------

    def clip_record_start(self) -> None:
        """Begin buffering frames for a training clip (bypasses the VSR path)."""
        with self._buf_lock:
            self.utterance = []
        self.recording = True

    def clip_record_stop(self):
        """Stop and return the buffered RGB frames (T,H,W,3)."""
        self.recording = False
        with self._buf_lock:
            frames = self.utterance
            self.utterance = []
        return frames

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
            self.last_frames = arr   # keep for "add to training"
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

        # Optional LLM cleanup of lipreading errors. Never block on failure —
        # fall back to the raw transcript and surface the reason.
        from .corrector import NoopCorrector

        if self.corrector is not None and not isinstance(self.corrector, NoopCorrector):
            self._set_state(self.BUSY)
            self._set_status("polishing text…")
            try:
                text = (self.corrector.correct(text) or text).strip()
            except Exception as e:
                self._set_status(f"cleanup skipped: {e}")

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
            self._set_status("synthesizing voice…")
            wav = self.tts.synthesize_to_wav(text)
            self._set_status("speaking…")
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
