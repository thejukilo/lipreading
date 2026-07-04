"""Mirror the physical webcam into a virtual camera so Google Meet can see it
while the app reads your lips.

A webcam is single-owner on Windows: whoever opens it first locks everyone else
out. So instead of fighting Meet for the device, the app becomes the *only*
owner of the physical camera and re-publishes every frame to a virtual camera
that Meet selects. It's the video twin of the VB-Cable audio split:

    audio:  app → "CABLE Input"  → Meet records "CABLE Output"
    video:  app → "OBS Virtual Camera" → Meet selects "OBS Virtual Camera"

Backed by pyvirtualcam, which on Windows uses the **OBS Virtual Camera**
DirectShow filter (installed with OBS Studio >= 26.1) or Unity Capture. The app
is the producer; Meet is the consumer — no device conflict.
"""

from __future__ import annotations


class VirtualCamera:
    """Lazily-opened virtual-camera sink. A safe no-op if unavailable.

    Opens on the first frame (so it matches the real capture resolution), then
    forwards each BGR frame. Any failure sets ``error`` and disables it rather
    than crashing the capture loop — the webcam preview and lipreading keep
    working even if the virtual camera can't start.
    """

    def __init__(self) -> None:
        self._cam = None
        self._size = None
        self.error: str | None = None
        self.active = False

    def send_bgr(self, frame_bgr, fps: int = 30) -> None:
        """Send one OpenCV BGR frame; opens the device at its size on first use."""
        if self.error is not None:
            return
        try:
            import cv2

            h, w = frame_bgr.shape[:2]
            if self._cam is None:
                self._open(w, h, fps)
                if self._cam is None:
                    return
            elif self._size != (w, h):
                return  # resolution changed mid-stream — ignore stray frame
            self._cam.send(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        except Exception as e:
            self.error = str(e)
            self.close()

    def _open(self, w: int, h: int, fps: int) -> None:
        try:
            import pyvirtualcam
        except ImportError:
            self.error = (
                "pyvirtualcam not installed — run `pip install pyvirtualcam` "
                "(and install OBS Studio, which provides the virtual-camera backend)."
            )
            return
        try:
            self._cam = pyvirtualcam.Camera(
                width=int(w), height=int(h), fps=int(fps) or 30, print_fps=False
            )
            self._size = (w, h)
            self.active = True
        except Exception as e:
            self._cam = None
            self.error = (
                f"could not start the virtual camera: {e}. Install OBS Studio "
                "(gives you 'OBS Virtual Camera'), and make sure OBS isn't already "
                "running its own virtual camera."
            )

    @property
    def device_name(self) -> str | None:
        return getattr(self._cam, "device", None) if self._cam is not None else None

    def close(self) -> None:
        cam, self._cam = self._cam, None
        self.active = False
        if cam is not None:
            try:
                cam.close()
            except Exception:
                pass
