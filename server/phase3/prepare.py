"""Scan the Dutch clip folder, pair each mp4 with its transcript, and split into
train/val/test **by source video** so no speaker leaks across the split.

Each clip is named like ``<videoid>_<seg>_scene000_track004.mp4`` with a sibling
``.txt`` holding the transcript. The ``<videoid>`` (the part before the first
``_``) identifies the source YouTube video; whole videos are assigned to one
split, which keeps the test set speaker-independent and the WER honest.

Run:  ``python -m server.phase3.prepare --data-dir path/to/clips``
Writes ``manifest.json`` (used by train.py / evaluate.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re

_UUID_PREFIX = re.compile(r"^[0-9a-fA-F]{8}-")


def video_id_of(stem: str) -> str:
    """Source-video id = the token before the first '_' (a stray upload-hash
    prefix like 'a3f6a488-' is stripped first)."""
    stem = _UUID_PREFIX.sub("", stem)
    return stem.split("_", 1)[0] or stem


def _bucket(video_id: str, seed: int) -> float:
    """Stable 0..1 hash of a video id (deterministic split, no RNG state)."""
    h = hashlib.sha1(f"{seed}:{video_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _clip_meta(path: str):
    """(frames, fps) via OpenCV; (0, 0) if unreadable."""
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0, 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return n, fps


def build_manifest(data_dir: str, val_frac: float = 0.08, test_frac: float = 0.12,
                   min_frames: int = 8, seed: int = 1234, probe: bool = True) -> dict:
    data_dir = os.path.abspath(data_dir)
    mp4s = []
    for root, _, files in os.walk(data_dir):
        for fn in files:
            if fn.lower().endswith(".mp4"):
                mp4s.append(os.path.join(root, fn))
    mp4s.sort()
    if not mp4s:
        raise RuntimeError(f"No .mp4 clips found under {data_dir}")

    entries, skipped = [], {"no_txt": 0, "empty": 0, "too_short": 0, "unreadable": 0}
    for i, mp4 in enumerate(mp4s):
        stem = os.path.splitext(os.path.basename(mp4))[0]
        txt = os.path.join(os.path.dirname(mp4), stem + ".txt")
        if not os.path.isfile(txt):
            skipped["no_txt"] += 1
            continue
        with open(txt, encoding="utf-8") as f:
            transcript = " ".join(f.read().split())
        if not transcript:
            skipped["empty"] += 1
            continue
        frames, fps = _clip_meta(mp4) if probe else (min_frames, 25.0)
        if probe and frames == 0:
            skipped["unreadable"] += 1
            continue
        if frames and frames < min_frames:
            skipped["too_short"] += 1
            continue
        entries.append({
            "clip": os.path.relpath(mp4, data_dir),
            "video_id": video_id_of(stem),
            "frames": frames, "fps": round(fps, 3),
            "transcript": transcript,
        })
        if probe and (i + 1) % 500 == 0:
            print(f"  scanned {i + 1}/{len(mp4s)}…")

    # Split whole videos by their stable hash bucket.
    vids = sorted({e["video_id"] for e in entries})
    split_of = {}
    for v in vids:
        b = _bucket(v, seed)
        split_of[v] = "test" if b < test_frac else "val" if b < test_frac + val_frac else "train"
    for e in entries:
        e["split"] = split_of[e["video_id"]]

    manifest = {
        "data_dir": data_dir,
        "seed": seed,
        "entries": entries,
        "summary": _summary(entries, vids, split_of, skipped),
    }
    return manifest


def _summary(entries, vids, split_of, skipped) -> dict:
    out = {"clips": len(entries), "videos": len(vids), "skipped": skipped, "splits": {}}
    for sp in ("train", "val", "test"):
        rows = [e for e in entries if e["split"] == sp]
        secs = sum((e["frames"] or 0) / (e["fps"] or 25.0) for e in rows)
        out["splits"][sp] = {
            "clips": len(rows),
            "videos": sum(1 for v in vids if split_of[v] == sp),
            "hours": round(secs / 3600.0, 2),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a train/val/test manifest for Dutch clips.")
    ap.add_argument("--data-dir", required=True, help="Folder of *.mp4 + *.txt clips.")
    ap.add_argument("--out", default="checkpoints/dutch/manifest.json")
    ap.add_argument("--val-frac", type=float, default=0.08)
    ap.add_argument("--test-frac", type=float, default=0.12)
    ap.add_argument("--min-frames", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--no-probe", action="store_true",
                    help="Skip opening each clip to read frame count/fps (faster, less filtering).")
    args = ap.parse_args(argv)

    print(f"[prepare] scanning {args.data_dir} …")
    manifest = build_manifest(
        args.data_dir, val_frac=args.val_frac, test_frac=args.test_frac,
        min_frames=args.min_frames, seed=args.seed, probe=not args.no_probe,
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    s = manifest["summary"]
    print(f"\n[prepare] {s['clips']} clips from {s['videos']} videos "
          f"(skipped: {s['skipped']})")
    for sp, d in s["splits"].items():
        print(f"  {sp:5}: {d['clips']:5} clips | {d['videos']:3} videos | {d['hours']:.2f} h")
    print(f"[prepare] wrote {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
