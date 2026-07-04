"""Dataset over the pre-cropped Dutch clips + auto_avsr's collate.

Clips are already 96x96, 25 fps, mouth-cropped, so there is no landmark/crop step:
read the mp4 -> (T,96,96,3) -> auto_avsr VideoTransform -> model. Labels are the
Dutch transcript **uppercased** before tokenizing, because auto_avsr's
SentencePiece vocabulary is uppercase (LRS3); lowercase would map to <unk>.
"""

from __future__ import annotations

import os


def _pad(samples, pad_val=0.0):
    import torch

    lengths = [len(s) for s in samples]
    max_size = max(lengths)
    sample_shape = list(samples[0].shape[1:])
    collated = samples[0].new_zeros([len(samples), max_size] + sample_shape)
    for i, sample in enumerate(samples):
        diff = len(sample) - max_size
        collated[i] = sample if diff == 0 else torch.cat(
            [sample, sample.new_full([-diff] + sample_shape, pad_val)]
        )
    if len(samples[0].shape) == 1:
        collated = collated.unsqueeze(1)
    return collated, lengths


def collate_pad(batch):
    import torch

    batch = [b for b in batch if b is not None]
    out = {}
    for key in batch[0].keys():
        pad_val = -1 if key == "target" else 0.0
        c, lens = _pad([s[key] for s in batch], pad_val)
        out[key + "s"] = c
        out[key + "_lengths"] = torch.tensor(lens)
    return out


def _read_clip(path):
    """mp4 -> (T,96,96,3) uint8 RGB via OpenCV."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(path)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
    cap.release()
    return np.asarray(frames, dtype=np.uint8)


class PreparedClipDataset:
    """torch-style dataset. ``entries`` are manifest rows for one split."""

    def __init__(self, data_dir, entries, video_transform, text_transform):
        import torch  # noqa: F401 — fail early if torch is missing

        self.data_dir = data_dir
        self.entries = entries
        self.video_transform = video_transform
        self.text_transform = text_transform

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, idx):
        import torch

        e = self.entries[idx]
        arr = _read_clip(os.path.join(self.data_dir, e["clip"]))
        if arr.shape[0] < 1:
            return None
        vid = torch.tensor(arr).permute(0, 3, 1, 2)         # (T,3,96,96)
        tokens = self.text_transform.tokenize(e["transcript"].upper())
        return {"input": self.video_transform(vid), "target": tokens}
