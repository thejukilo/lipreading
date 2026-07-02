"""Device discovery for the setup UI: cameras + audio outputs."""

from __future__ import annotations

import os
import sys

# Quiet OpenCV's native VideoIO log spam (the 'obsensor index out of range' /
# 'can't capture by index' lines while probing). Must be set before cv2 loads.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

from .audio_out import list_output_devices


def _camera_backends():
    """Backends to try, best-first. On Windows try DSHOW first because that's
    how we enumerate names (pygrabber) — so the index matches the picked name —
    then MSMF, then whatever OpenCV picks."""
    import cv2

    if sys.platform.startswith("win"):
        return [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("ANY", cv2.CAP_ANY)]
    return [("ANY", cv2.CAP_ANY)]


def open_camera(index: int, width: int = 640, height: int = 480):
    """Open camera ``index`` trying each backend, validating with a real read.

    Returns ``(cap, backend_name)`` or ``(None, None)`` if none work. Some
    cameras (esp. the Logitech BRIO) take a moment to deliver the first frame,
    so we retry the read for ~1.5s before giving up. Validating a frame avoids
    handing back a half-open capture (which can crash the reader thread).
    """
    import time

    import cv2

    for name, backend in _camera_backends():
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, 25)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            for _ in range(30):  # ~1.5s warm-up window
                ok, frame = cap.read()
                if ok and frame is not None:
                    return cap, name
                time.sleep(0.05)
        cap.release()
    return None, None


def _windows_camera_names() -> list[str]:
    """Real device names in DirectShow order (matches CAP_DSHOW index)."""
    try:
        import comtypes

        comtypes.CoInitialize()  # we may be on a worker thread
    except Exception:
        pass
    from pygrabber.dshow_graph import FilterGraph

    return FilterGraph().get_input_devices()


def list_cameras(max_index: int = 6) -> list[tuple[int, str]]:
    """Return [(index, name), ...] of available cameras.

    On Windows we read the real device names (Logitech BRIO, etc.) via DirectShow
    — fast, no camera opening — just like the list Google Meet shows. Elsewhere
    (or if that fails) we fall back to probing indices by opening them.
    """
    if sys.platform.startswith("win"):
        try:
            names = _windows_camera_names()
            if names:
                return [(i, name) for i, name in enumerate(names)]
        except Exception as e:
            # Make the reason visible instead of silently showing "Camera 0".
            print(f"[devices] real camera names unavailable ({type(e).__name__}: {e}). "
                  "Install pygrabber for names:  pip install pygrabber")

    found = []
    for idx in range(max_index):
        cap, name = open_camera(idx)
        if cap is not None:
            found.append((idx, f"Camera {idx} ({name})"))
            cap.release()
    return found


def list_audio_outputs() -> list[tuple[int, str]]:
    """(index, name) for playback-capable audio devices."""
    return [(idx, name) for idx, name, _ch in list_output_devices()]
