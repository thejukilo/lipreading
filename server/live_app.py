"""Live push-to-talk lipreading — terminal + OpenCV view.

A thin front-end over ``LiveSession`` (the GUI, ``server.gui_app``, is the
friendly alternative). Same loop: hold a key and mouth a sentence -> transcribe
-> review -> speak into the VB-Cable virtual mic so Meet hears it.

Controls
--------
- Hold the push-to-talk key (default: RIGHT CTRL) while mouthing; release to end.
- Review (default): focus this window, then
    Enter = speak into Meet   Esc = discard   e = edit text in the terminal
- ``--auto-speak`` speaks immediately (no review).
- m = toggle the local monitor (hear it on your speakers).  Q = quit.
"""

from __future__ import annotations

import argparse
import os
import time

from .hotkey import PushToTalkListener
from .session import LiveSession, SessionConfig


def _render(session: LiveSession, key_label: str):
    import cv2
    import numpy as np

    frame = session.latest_bgr
    if frame is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame = frame.copy()
    h, w = frame.shape[:2]

    banner = {
        LiveSession.IDLE: (f"Hold [{key_label}] to speak", (60, 200, 60)),
        LiveSession.RECORDING: ("● REC — mouth your sentence", (40, 40, 235)),
        LiveSession.BUSY: ("… transcribing", (0, 180, 235)),
        LiveSession.REVIEW: ("REVIEW  Enter=speak  Esc=discard  e=edit", (235, 180, 0)),
        LiveSession.SPEAKING: ("♪ speaking into Meet", (235, 120, 0)),
    }
    text, color = banner.get(session.state, ("", (255, 255, 255)))
    cv2.rectangle(frame, (0, 0), (w, 30), (30, 30, 30), -1)
    cv2.putText(frame, text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    if session.state == LiveSession.RECORDING:
        cv2.putText(frame, f"{session.frame_count} frames", (w - 110, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    mon = "monitor ON (m)" if session.monitor_on else "monitor OFF (m)"
    mcol = (60, 200, 60) if session.monitor_on else (120, 120, 120)
    cv2.putText(frame, mon, (w - 160, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, mcol, 1)

    if session.state == LiveSession.REVIEW and session.pending_text:
        _draw_wrapped(frame, session.pending_text, y0=h - 70)
    if session.last_status:
        cv2.putText(frame, session.last_status[:70], (8, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 235), 1)
    return frame


def _draw_wrapped(frame, text, y0):
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


def _handle_review_key(session: LiveSession, key: int) -> None:
    if key in (13, 10):            # Enter -> speak
        session.speak(session.pending_text)
    elif key == 27:                # Esc -> discard
        session.discard()
    elif key in (ord("e"), ord("E")):  # edit in terminal
        print(f"\n[edit] current: {session.pending_text}")
        try:
            edited = input("[edit] new text (blank = keep): ").strip()
        except EOFError:
            edited = ""
        session.speak(edited or session.pending_text)


def _cfg_from_args(a) -> SessionConfig:
    return SessionConfig(
        checkpoint=a.checkpoint,
        auto_avsr_dir=a.auto_avsr_dir,
        detector=a.detector,
        device=a.device,
        camera=a.camera,
        width=a.width,
        height=a.height,
        tts=a.tts,
        voice=a.voice or a.tts,
        output_device=a.output_device,
        monitor_device=a.monitor_device,
        monitor_on=not a.no_monitor,
        auto_speak=a.auto_speak,
        ptt_key=a.key,
    )


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
    p.add_argument("--voice", default=None,
                   help="Voice selector: piper | sapi | clone:<slug> (default: --tts value).")
    p.add_argument("--output-device", default="CABLE Input",
                   help="Playback device name substring or index (default: VB-Cable).")
    p.add_argument("--monitor-device", default=None,
                   help="Speakers/headphones for the monitor (name substring or index).")
    p.add_argument("--auto-speak", action="store_true",
                   help="Speak immediately on release (skip review).")
    p.add_argument("--no-monitor", action="store_true",
                   help="Do NOT also play to your speakers.")
    p.add_argument("--list-audio-devices", action="store_true",
                   help="List playback devices and exit.")
    return p


def main() -> int:
    import cv2

    args = _build_parser().parse_args()
    if args.list_audio_devices:
        from .audio_out import print_output_devices

        print_output_devices()
        return 0

    session = LiveSession(_cfg_from_args(args))
    print(f"[live] loading model ({args.checkpoint}) — this takes a moment...")
    session.load()
    session.start()

    listener = PushToTalkListener(args.key, session.start_recording, session.stop_recording)
    listener.start()

    win = "Lipreading — push to talk"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    print(f"[live] ready. Hold [{args.key}] and mouth a sentence. Q to quit.")
    try:
        while True:
            cv2.imshow(win, _render(session, args.key))
            key = cv2.waitKey(15) & 0xFF
            if key in (ord("q"), ord("Q")):
                break
            if key in (ord("m"), ord("M")):
                session.toggle_monitor()
            elif session.state == LiveSession.REVIEW and key != 255:
                _handle_review_key(session, key)
            time.sleep(0.001)
    finally:
        listener.stop()
        session.shutdown()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
