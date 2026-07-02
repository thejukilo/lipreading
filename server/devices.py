"""Device discovery for the setup UI: cameras + audio outputs."""

from __future__ import annotations

import sys

from .audio_out import list_output_devices


def _camera_backends():
    """Backends to try, best-first. On Windows MSMF is usually the reliable one;
    DSHOW often warns 'can't be used to capture by index'. Try MSMF, then DSHOW,
    then whatever OpenCV picks."""
    import cv2

    if sys.platform.startswith("win"):
        return [("MSMF", cv2.CAP_MSMF), ("DSHOW", cv2.CAP_DSHOW), ("ANY", cv2.CAP_ANY)]
    return [("ANY", cv2.CAP_ANY)]


def open_camera(index: int, width: int = 640, height: int = 480):
    """Open camera ``index`` trying each backend, validating with a real read.

    Returns ``(cap, backend_name)`` or ``(None, None)`` if none work. Validating
    a frame read avoids handing back a half-open capture (which can crash the
    reader thread on Windows).
    """
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
            for _ in range(10):  # give the device a moment to deliver a frame
                ok, frame = cap.read()
                if ok and frame is not None:
                    return cap, name
        cap.release()
    return None, None


def list_cameras(max_index: int = 6) -> list[tuple[int, str]]:
    """Probe camera indices and return [(index, label), ...] for ones that open.

    OpenCV can't read friendly camera names cross-platform, so labels are
    generic ("Camera 0 (MSMF)"). Probing opens each device briefly, so close
    other apps using the webcam first for an accurate list.
    """
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
