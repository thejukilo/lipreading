"""Live push-to-talk lipreading app (Phase 1, step 2 + 3 + 4).

Loop: hold a key and mouth a sentence at the webcam -> release -> the VSR model
transcribes it -> review it -> it's synthesized and played into the VB-Cable
virtual mic, so Google Meet hears it as your voice.

Controls
--------
- Hold the push-to-talk key (default: RIGHT CTRL) while mouthing. Release to end.
- In review (default mode): focus this window, then
    Enter = speak into Meet   Esc = discard   e = edit text in the terminal
- ``--auto-speak`` skips review and speaks immediately (hands-free, stays in Meet).
- Press Q in the window (or Ctrl-C in the terminal) to quit.

25 fps: frames are sampled at 25 fps to match auto_avsr's training rate.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time


# ---- push-to-talk key resolution (pynput) ---------------------------------

def _resolve_key(name: str):
    from pynput import keyboard

    named = {
        "ctrl": keyboard.Key.ctrl, "ctrl_l": keyboard.Key.ctrl_l,
        "ctrl_r": keyboard.Key.ctrl_r, "alt": keyboard.Key.alt,
        "alt_l": keyboard.Key.alt_l, "alt_r": keyboard.Key.alt_r,
        "shift": keyboard.Key.shift, "shift_r": keyboard.Key.shift_r,
        "space": keyboard.Key.space,
        "f7": keyboard.Key.f7, "f8": keyboard.Key.f8, "f9": keyboard.Key.f9,
        "f10": keyboard.Key.f10,
    }
    if name in named:
        return named[name]
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise ValueError(f"Unsupported --key '{name}'. Try a single letter or one of: "
                     f"{', '.join(sorted(named))}.")


def _key_matches(pressed, target) -> bool:
    """Match, treating the generic ctrl/alt/shift as either side."""
    from pynput import keyboard

    if pressed == target:
        return True
    fam = {
        keyboard.Key.ctrl: {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
        keyboard.Key.alt: {keyboard.Key.alt_l, keyboard.Key.alt_r, getattr(keyboard.Key, "alt_gr", None)},
        keyboard.Key.shift: {keyboard.Key.shift_l, keyboard.Key.shift_r},
    }
    return pressed in fam.get(target, set())


class LiveApp:
    # UI states
    IDLE, RECORDING, BUSY, REVIEW, SPEAKING = "idle", "recording", "busy", "review", "speaking"

    def __init__(self, args) -> None:
        self.args = args
        self.state = self.IDLE
        self.recording = False
        self._key_held = False
        self.buf_lock = threading.Lock()
        self.utterance = []          # list of RGB frames while recording
        self.latest_bgr = None       # newest frame for preview
        self.pending_text = ""       # transcript awaiting review
        self.status_msg = ""
        self.running = True
        self.monitor_on = not args.no_monitor   # toggled with 'm' at runtime
        self.target_key = _resolve_key(args.key)

        # Lazily-built heavy bits (loaded in setup()).
        self.engine = None
        self.tts = None
        self.cap = None
        self.out_device = None

    # ---- setup ------------------------------------------------------------

    def setup(self) -> None:
        import cv2

        from .audio_out import resolve_output_device
        from .engine import LipreadingEngine
        from .tts import make_tts

        print(f"[live] loading VSR model ({self.args.checkpoint}) — this takes a moment...")
        self.engine = LipreadingEngine(
            checkpoint_path=self.args.checkpoint,
            auto_avsr_dir=self.args.auto_avsr_dir,
            detector=self.args.detector,
            device=self._device(),
        )
        print("[live] model ready.")

        self.tts = make_tts(self.args.tts)
        self.out_device = resolve_output_device(self.args.output_device)
        dev_desc = self.args.output_device if self.out_device is not None else "system default"
        print(f"[live] TTS={self.args.tts}  audio-out={dev_desc}")

        cam_api = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0
        self.cap = cv2.VideoCapture(self.args.camera, cam_api)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open camera index {self.args.camera}.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.args.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.args.height)
        self.cap.set(cv2.CAP_PROP_FPS, 25)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep latency low
        except Exception:
            pass

    def _device(self) -> str:
        if self.args.device:
            return self.args.device
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"

    # ---- capture thread ---------------------------------------------------

    def _capture_loop(self) -> None:
        import cv2

        period = 1.0 / 25.0
        next_keep = time.monotonic()
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.005)
                continue
            self.latest_bgr = frame
            now = time.monotonic()
            if now >= next_keep:
                next_keep = max(next_keep + period, now - period)  # 25 fps cadence
                if self.recording:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    with self.buf_lock:
                        self.utterance.append(rgb)

    # ---- push-to-talk (pynput) -------------------------------------------

    def _on_press(self, key) -> None:
        if not _key_matches(key, self.target_key):
            return
        if self._key_held or self.state != self.IDLE:
            return  # ignore auto-repeat, or presses while busy/review/speaking
        self._key_held = True
        with self.buf_lock:
            self.utterance = []
        self.recording = True
        self.state = self.RECORDING

    def _on_release(self, key) -> None:
        if not _key_matches(key, self.target_key) or not self._key_held:
            return
        self._key_held = False
        self.recording = False
        if self.state != self.RECORDING:
            return
        with self.buf_lock:
            frames = self.utterance
            self.utterance = []
        self.state = self.BUSY
        threading.Thread(target=self._transcribe_worker, args=(frames,), daemon=True).start()

    # ---- workers ----------------------------------------------------------

    def _transcribe_worker(self, frames) -> None:
        import numpy as np

        try:
            arr = np.asarray(frames, dtype=np.uint8)
            t0 = time.perf_counter()
            text = self.engine.transcribe_frames(arr)
            dt = time.perf_counter() - t0
        except Exception as e:  # short clip, no face, etc.
            self.status_msg = f"! {e}"
            self.state = self.IDLE
            return

        text = (text or "").strip()
        print(f"[live] transcript ({len(frames)} frames, {dt:.1f}s): {text!r}")
        if not text:
            self.status_msg = "! empty transcript — try again"
            self.state = self.IDLE
            return

        if self.args.auto_speak:
            self._speak(text)
        else:
            self.pending_text = text
            self.status_msg = ""
            self.state = self.REVIEW

    def _speak(self, text: str) -> None:
        self.state = self.SPEAKING
        threading.Thread(target=self._speak_worker, args=(text,), daemon=True).start()

    def _speak_worker(self, text: str) -> None:
        from .audio_out import play_wav

        try:
            wav = self.tts.synthesize_to_wav(text)
            play_wav(
                wav,
                device=self.out_device,
                monitor=self.monitor_on,
                monitor_device=self.args.monitor_device,
                blocking=True,
            )
            try:
                os.remove(wav)
            except OSError:
                pass
        except Exception as e:
            self.status_msg = f"! TTS/playback failed: {e}"
        finally:
            self.state = self.IDLE

    # ---- review-mode key handling (from the OpenCV window) ----------------

    def _handle_review_key(self, key: int) -> None:
        if key in (13, 10):            # Enter -> speak
            text, self.pending_text = self.pending_text, ""
            self._speak(text)
        elif key == 27:                # Esc -> discard
            self.pending_text = ""
            self.status_msg = "discarded"
            self.state = self.IDLE
        elif key in (ord("e"), ord("E")):  # edit in terminal
            print(f"\n[edit] current: {self.pending_text}")
            try:
                edited = input("[edit] new text (blank = keep): ").strip()
            except EOFError:
                edited = ""
            text = edited or self.pending_text
            self.pending_text = ""
            self._speak(text)

    # ---- rendering --------------------------------------------------------

    def _render(self):
        import cv2
        import numpy as np

        frame = self.latest_bgr
        if frame is None:
            frame = np.zeros((self.args.height, self.args.width, 3), dtype=np.uint8)
        frame = frame.copy()
        h, w = frame.shape[:2]

        banner = {
            self.IDLE: (f"Hold [{self.args.key}] to speak", (60, 200, 60)),
            self.RECORDING: ("● REC — mouth your sentence", (40, 40, 235)),
            self.BUSY: ("… transcribing", (0, 180, 235)),
            self.REVIEW: ("REVIEW  Enter=speak  Esc=discard  e=edit", (235, 180, 0)),
            self.SPEAKING: ("♪ speaking into Meet", (235, 120, 0)),
        }
        text, color = banner.get(self.state, ("", (255, 255, 255)))
        cv2.rectangle(frame, (0, 0), (w, 30), (30, 30, 30), -1)
        cv2.putText(frame, text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        if self.state == self.RECORDING:
            with self.buf_lock:
                n = len(self.utterance)
            cv2.putText(frame, f"{n} frames", (w - 110, 21),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        mon_txt = "monitor ON (m)" if self.monitor_on else "monitor OFF (m)"
        mon_col = (60, 200, 60) if self.monitor_on else (120, 120, 120)
        cv2.putText(frame, mon_txt, (w - 160, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, mon_col, 1)

        if self.state == self.REVIEW and self.pending_text:
            self._draw_wrapped(frame, self.pending_text, y0=h - 70)
        if self.status_msg:
            cv2.putText(frame, self.status_msg[:70], (8, h - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 235), 1)
        return frame

    def _draw_wrapped(self, frame, text, y0):
        import cv2

        w = frame.shape[1]
        words, line, lines = text.split(), "", []
        for word in words:
            trial = (line + " " + word).strip()
            if len(trial) > (w // 11):
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        for i, ln in enumerate(lines[-3:]):
            cv2.putText(frame, ln, (8, y0 + i * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # ---- main loop --------------------------------------------------------

    def run(self) -> None:
        import cv2
        from pynput import keyboard

        self.setup()
        cap_thread = threading.Thread(target=self._capture_loop, daemon=True)
        cap_thread.start()

        listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        listener.start()

        win = "Lipreading — push to talk"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        print(f"[live] ready. Hold [{self.args.key}] and mouth a sentence. Q to quit.")
        try:
            while self.running:
                cv2.imshow(win, self._render())
                key = cv2.waitKey(15) & 0xFF
                if key in (ord("q"), ord("Q")):
                    break
                if key in (ord("m"), ord("M")):   # toggle local monitor anytime
                    self.monitor_on = not self.monitor_on
                    self.status_msg = f"monitor {'ON' if self.monitor_on else 'OFF'}"
                elif self.state == self.REVIEW and key != 255:
                    self._handle_review_key(key)
        finally:
            self.running = False
            listener.stop()
            if self.cap is not None:
                self.cap.release()
            cv2.destroyAllWindows()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Live push-to-talk lipreading -> voice into Meet.")
    p.add_argument("--checkpoint",
                   default=os.environ.get("VSR_CHECKPOINT", "checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth"))
    p.add_argument("--auto-avsr-dir", default=None)
    p.add_argument("--detector", default="mediapipe", choices=["mediapipe", "retinaface"])
    p.add_argument("--device", default=None, help="cuda:0 or cpu (default: auto).")
    p.add_argument("--camera", type=int, default=0, help="Webcam index.")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--key", default="ctrl_r", help="Push-to-talk key (default: right ctrl).")
    p.add_argument("--tts", default="piper", choices=["piper", "sapi"])
    p.add_argument("--output-device", default="CABLE Input",
                   help="Playback device name substring or index (default: VB-Cable). "
                        "Use --list-audio-devices to see names.")
    p.add_argument("--auto-speak", action="store_true",
                   help="Speak immediately on release (skip the review step).")
    p.add_argument("--no-monitor", action="store_true",
                   help="Do NOT also play to your speakers (default: you hear a monitor of what's sent to Meet).")
    p.add_argument("--monitor-device", default=None,
                   help="Speakers/headphones for the monitor (name substring or index; default: system default output).")
    p.add_argument("--list-audio-devices", action="store_true",
                   help="List playback devices and exit.")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    if args.list_audio_devices:
        from .audio_out import print_output_devices

        print_output_devices()
        return 0
    LiveApp(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
