"""Face-landmark detector on mediapipe's current Tasks API.

Why this exists: auto_avsr's bundled mediapipe detector uses the legacy
``mp.solutions.face_detection`` API, which Google **removed** in mediapipe
0.10.x (>= ~0.10.18). On current mediapipe (e.g. 0.10.35) ``mp.solutions`` does
not exist at all, so auto_avsr's detector raises
``AttributeError: module 'mediapipe' has no attribute 'solutions'``.

The Tasks ``FaceDetector`` returns BlazeFace's 6 keypoints; the first four are
right-eye, left-eye, nose-tip, mouth-center — the exact 4 points (and order)
that auto_avsr's ``VideoProcess`` expects. So this is a drop-in replacement for
the landmarks detector: same call signature, same per-frame output
(``None`` or a ``(4, 2)`` int array), paired with the unchanged ``VideoProcess``.
"""

from __future__ import annotations

import os

import numpy as np

# Official mediapipe short-range BlazeFace model (good to ~2 m — fine for a
# webcam and the demo clip). Downloaded by the setup scripts.
BLAZE_FACE_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)


class MediapipeTasksLandmarksDetector:
    """Drop-in for auto_avsr's mediapipe ``LandmarksDetector`` (Tasks API)."""

    def __init__(
        self,
        model_path: str | None = None,
        min_detection_confidence: float = 0.5,
    ) -> None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        model_path = model_path or os.environ.get(
            "BLAZE_FACE_MODEL", "models/blaze_face_short_range.tflite"
        )
        model_path = os.path.abspath(model_path)
        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"BlazeFace model not found: {model_path}\n"
                f"Download it (setup scripts do this) from:\n  {BLAZE_FACE_URL}"
            )

        self._mp = mp
        options = mp_vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=mp_vision.RunningMode.IMAGE,
            min_detection_confidence=min_detection_confidence,
        )
        self._detector = mp_vision.FaceDetector.create_from_options(options)

    def __call__(self, video_frames) -> list:
        """RGB uint8 frames (T,H,W,3) -> list of ``(4,2)`` int arrays or None."""
        landmarks = []
        for frame in video_frames:
            landmarks.append(self._detect_frame(frame))
        if all(lm is None for lm in landmarks):
            raise RuntimeError(
                "Cannot detect a face in any frame — check framing/lighting and "
                "that a front-facing mouth is visible."
            )
        return landmarks

    def _detect_frame(self, frame):
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        ih, iw = frame.shape[:2]
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=frame)
        result = self._detector.detect(mp_image)
        if not result.detections:
            return None

        # Largest detected face (matches auto_avsr's max-bbox selection).
        best = max(
            result.detections,
            key=lambda d: d.bounding_box.width * d.bounding_box.height,
        )
        # BlazeFace keypoint order: [right_eye, left_eye, nose_tip, mouth_center,
        # right_ear, left_ear]. VideoProcess needs the first four.
        kps = best.keypoints[:4]
        if len(kps) < 4:
            return None
        return np.array(
            [[int(round(kp.x * iw)), int(round(kp.y * ih))] for kp in kps],
            dtype=np.int32,
        )
