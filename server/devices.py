"""Device discovery for the setup UI: cameras + audio outputs."""

from __future__ import annotations

import sys

from .audio_out import list_output_devices


def list_cameras(max_index: int = 6) -> list[tuple[int, str]]:
    """Probe camera indices and return [(index, label), ...] for ones that open.

    OpenCV can't read friendly camera names cross-platform, so labels are
    generic ("Camera 0"). Probing opens each device briefly, so close other apps
    using the webcam first for an accurate list.
    """
    import cv2

    cam_api = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0
    found = []
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, cam_api)
        ok = cap.isOpened()
        if ok:
            ok2, _ = cap.read()
            if ok2:
                found.append((idx, f"Camera {idx}"))
        cap.release()
    return found


def list_audio_outputs() -> list[tuple[int, str]]:
    """(index, name) for playback-capable audio devices."""
    return [(idx, name) for idx, name, _ch in list_output_devices()]
