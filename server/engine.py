"""Lipreading inference engine — a thin wrapper around auto_avsr.

We reuse auto_avsr's ``ModelModule`` (Conformer VSR), its sentencepiece
tokenizer, its vendored ESPnet decoder, and its mouth-cropping detectors.
auto_avsr is not a pip package: the whole repo must be importable, because
``datamodule.transforms`` resolves the tokenizer relative to the repo root
(``spm/unigram/unigram5000.model``) and ``lightning.ModelModule`` imports the
vendored ``espnet`` package. So we clone auto_avsr and put it on ``sys.path``.

The auto_avsr ``InferencePipeline`` only exists inside a demo notebook, so we
reimplement it here — faithful to the notebook, but with real device placement
(the notebook leaves the model on CPU).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def normalize_transcript(text: str) -> str:
    """Turn the model's ALL-CAPS output into natural sentence case.

    auto_avsr (LRS3) emits uppercase text; TTS engines then spell short words
    like "IT" letter by letter ("I-T"). Lowercasing fixes the pronunciation;
    we then re-capitalize sentence starts and the standalone pronoun "I" for
    readability in the review box.
    """
    import re

    text = (text or "").strip()
    if not text:
        return text
    letters = [c for c in text if c.isalpha()]
    if not (letters and all(c.isupper() for c in letters)):
        return text  # not all-caps — leave as-is

    text = text.lower()
    text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    text = re.sub(r"\bi\b", "I", text)      # standalone pronoun
    text = re.sub(r"\bi'", "I'", text)      # I'm, I'll, I've, ...
    return text


def _ensure_auto_avsr_on_path(auto_avsr_dir: str) -> None:
    """Put the auto_avsr checkout at the front of sys.path.

    Front, not append: auto_avsr ships a root ``lightning.py`` that we want to
    resolve before the pip ``lightning`` package (they collide by name).
    """
    d = os.path.abspath(auto_avsr_dir)
    if not os.path.isdir(d):
        raise FileNotFoundError(
            f"auto_avsr checkout not found at '{d}'.\n"
            "Clone it first (see scripts/setup_windows.ps1) or pass "
            "auto_avsr_dir=... / set AUTO_AVSR_DIR."
        )
    if not os.path.isfile(os.path.join(d, "lightning.py")):
        raise FileNotFoundError(
            f"'{d}' does not look like an auto_avsr checkout (no lightning.py)."
        )
    if d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)


class LipreadingEngine:
    """Video file -> transcript, using an auto_avsr VSR checkpoint.

    Parameters
    ----------
    checkpoint_path:
        Path to a ``.pth`` VSR checkpoint from the auto_avsr model zoo
        (e.g. ``vsr_trlrs3_base.pth``).
    auto_avsr_dir:
        Path to the auto_avsr repo checkout. Falls back to ``$AUTO_AVSR_DIR``.
    detector:
        ``"mediapipe"`` (default; pip-installable, easiest on Windows) or
        ``"retinaface"`` (needs the ibug packages, GPU-oriented).
    device:
        ``"cuda:0"`` or ``"cpu"``.
    """

    # Fewer frames than this can't be smoothed/cropped meaningfully by
    # VideoProcess (window_margin) or read by the model. ~0.3s at 25 fps.
    MIN_FRAMES = 8

    def __init__(
        self,
        checkpoint_path: str,
        auto_avsr_dir: str | None = None,
        detector: str = "mediapipe",
        device: str = "cuda:0",
    ) -> None:
        auto_avsr_dir = auto_avsr_dir or os.environ.get("AUTO_AVSR_DIR", "third_party/auto_avsr")
        _ensure_auto_avsr_on_path(auto_avsr_dir)
        self.auto_avsr_dir = os.path.abspath(auto_avsr_dir)

        checkpoint_path = os.path.abspath(checkpoint_path)
        if not os.path.isfile(checkpoint_path):
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
        self.checkpoint_path = checkpoint_path
        self.detector = detector
        self.device = device

        # Imports are deferred until after sys.path is patched.
        import torch  # noqa: F401  (kept local so import errors are actionable)

        self._torch = torch
        self._build(detector, device)

    def _build(self, detector: str, device: str) -> None:
        import torch
        from datamodule.transforms import VideoTransform
        from lightning import ModelModule

        # The demo notebook works with only `modality` set; ModelModule reads
        # every other field via getattr(..., default), so a bare Namespace is
        # enough for inference against the base checkpoint.
        args = argparse.Namespace(modality="video")

        if detector == "mediapipe":
            # auto_avsr's own mediapipe detector uses the legacy
            # `mp.solutions` API, which Google removed in mediapipe >= ~0.10.18.
            # We substitute a Tasks-API detector with an identical output
            # format and keep auto_avsr's VideoProcess (it needs its bundled
            # 20words_mean_face.npy, resolved relative to that module).
            from preparation.detectors.mediapipe.video_process import VideoProcess

            from .detectors import MediapipeTasksLandmarksDetector

            self.landmarks_detector = MediapipeTasksLandmarksDetector()
            self.video_process = VideoProcess(convert_gray=False)
        elif detector == "retinaface":
            from preparation.detectors.retinaface.detector import LandmarksDetector
            from preparation.detectors.retinaface.video_process import VideoProcess

            self.landmarks_detector = LandmarksDetector(device=device)
            self.video_process = VideoProcess(convert_gray=False)
        else:
            raise ValueError(f"Unknown detector: {detector!r} (use 'mediapipe' or 'retinaface')")

        self.video_transform = VideoTransform(subset="test")

        # weights_only=False explicitly: the auto_avsr checkpoint is a trusted
        # local file, and torch 2.6 flips the default to True (which would break
        # this load). Also silences the FutureWarning.
        ckpt = torch.load(self.checkpoint_path, map_location="cpu", weights_only=False)
        self.modelmodule = ModelModule(args)
        self.modelmodule.model.load_state_dict(ckpt)
        self.modelmodule.eval()
        self.modelmodule.to(device)

    def _load_video(self, path: str):
        import torchvision

        # Returns THWC uint8 numpy (frames, height, width, channels).
        return torchvision.io.read_video(path, pts_unit="sec")[0].numpy()

    def transcribe(self, video_path: str) -> str:
        """Run mouth-crop + VSR on a video file and return decoded text."""
        video_path = os.path.abspath(video_path)
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        return self.transcribe_frames(self._load_video(video_path))

    def transcribe_frames(self, frames) -> str:
        """Run mouth-crop + VSR on in-memory frames and return decoded text.

        ``frames``: a ``(T, H, W, 3)`` uint8 numpy array of **RGB** frames,
        ideally at **25 fps** (auto_avsr was trained on 25 fps LRS3 clips —
        feeding another rate degrades accuracy). This is the shared path used by
        both the file smoke test and the live push-to-talk app.
        """
        import numpy as np
        import torch

        frames = np.ascontiguousarray(frames)
        if frames.ndim != 4 or frames.shape[-1] != 3:
            raise ValueError(
                f"Expected frames of shape (T,H,W,3) RGB uint8, got {frames.shape}."
            )
        if frames.shape[0] < self.MIN_FRAMES:
            raise RuntimeError(
                f"Only {frames.shape[0]} frame(s) captured — too short to read. "
                f"Hold the push-to-talk key longer (need >= {self.MIN_FRAMES})."
            )

        landmarks = self.landmarks_detector(frames)  # raises if no face anywhere
        video = self.video_process(frames, landmarks)  # cropped mouth ROI
        if video is None:
            raise RuntimeError("Mouth crop failed (no usable landmarks).")
        return self._decode_cropped(video)

    def transcribe_prepared_frames(self, frames) -> str:
        """Transcribe frames that are **already mouth-cropped** to 96x96.

        For datasets that ship in the model's native format (e.g. the Phase-3
        Dutch clips: 96x96, 25 fps, pre-cropped). Skips landmark detection and
        VideoProcess entirely — the frames go straight into the transform.
        ``frames``: ``(T, 96, 96, 3)`` uint8 RGB.
        """
        import numpy as np

        frames = np.ascontiguousarray(frames)
        if frames.ndim != 4 or frames.shape[-1] != 3:
            raise ValueError(f"Expected (T,96,96,3) RGB uint8, got {frames.shape}.")
        return self._decode_cropped(frames)

    def _decode_cropped(self, video_thwc) -> str:
        """Shared tail: a cropped (T,H,W,3) ROI -> transform -> model -> text."""
        import torch

        video = torch.tensor(video_thwc).permute(0, 3, 1, 2)  # T,C,H,W
        video = self.video_transform(video).to(self.device)
        with torch.no_grad():
            transcript = self.modelmodule(video)
        return normalize_transcript(transcript)


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Step 1 smoke test: transcribe a video clip with auto_avsr VSR."
    )
    parser.add_argument("--video", required=True, help="Path to the input video file.")
    parser.add_argument(
        "--checkpoint",
        default=os.environ.get("VSR_CHECKPOINT", "checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth"),
        help="Path to the VSR .pth checkpoint.",
    )
    parser.add_argument(
        "--auto-avsr-dir",
        default=None,
        help="Path to the auto_avsr checkout (default: $AUTO_AVSR_DIR or third_party/auto_avsr).",
    )
    parser.add_argument("--detector", default="mediapipe", choices=["mediapipe", "retinaface"])
    parser.add_argument("--device", default=None, help="cuda:0 or cpu (default: auto).")
    args = parser.parse_args()

    device = args.device
    if device is None:
        import torch

        device = "cuda:0" if torch.cuda.is_available() else "cpu"

    print(f"[smoke] device={device} detector={args.detector}")
    print(f"[smoke] checkpoint={args.checkpoint}")
    print(f"[smoke] video={args.video}")

    t0 = time.perf_counter()
    engine = LipreadingEngine(
        checkpoint_path=args.checkpoint,
        auto_avsr_dir=args.auto_avsr_dir,
        detector=args.detector,
        device=device,
    )
    t_load = time.perf_counter() - t0
    print(f"[smoke] model loaded in {t_load:.1f}s")

    t1 = time.perf_counter()
    transcript = engine.transcribe(args.video)
    t_infer = time.perf_counter() - t1

    print("\n===== TRANSCRIPT =====")
    print(transcript)
    print("======================")
    print(f"[smoke] inference {t_infer:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
