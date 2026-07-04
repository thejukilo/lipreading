"""Decode the held-out test split and report speaker-independent WER + CER.

Loads a trained Dutch checkpoint, transcribes each test clip through the model's
own decoder (via the prepared-frames path — no re-cropping, the clips are already
96x96), and scores against the reference transcripts. Also dumps sample
hyp/ref pairs so you can eyeball what the errors actually look like.

    python -m server.phase3.evaluate --manifest checkpoints/dutch/manifest.json \
        --checkpoint checkpoints/dutch/dutch_vsr.pth
"""

from __future__ import annotations

import argparse
import json
import os

from .data import _read_clip
from .metrics import corpus_wer


def evaluate(manifest_path, checkpoint, auto_avsr_dir=None, detector="mediapipe",
             device=None, split="test", limit=None, samples_out=None, on_progress=None):
    from ..engine import LipreadingEngine

    def msg(s):
        print(f"[eval] {s}", flush=True)  # flush so progress shows live on Windows
        if on_progress:
            on_progress(s)

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    data_dir = manifest["data_dir"]
    rows = [e for e in manifest["entries"] if e["split"] == split]
    if limit:
        rows = rows[:limit]
    if not rows:
        raise RuntimeError(f"No clips in split '{split}'.")
    msg(f"loading model from {os.path.basename(checkpoint)} …")
    engine = LipreadingEngine(checkpoint_path=checkpoint, auto_avsr_dir=auto_avsr_dir,
                              detector=detector, device=device or _auto_device(),
                              load_detector=False)
    msg(f"model on {engine.device} — decoding {len(rows)} '{split}' clips "
        "(first few shown so you can see it's alive)…")

    pairs, samples = [], []
    for i, e in enumerate(rows):
        arr = _read_clip(os.path.join(data_dir, e["clip"]))
        try:
            hyp = engine.transcribe_prepared_frames(arr)
        except Exception as ex:
            hyp = ""
            msg(f"  clip {e['clip']} failed: {ex}")
        ref = e["transcript"]
        pairs.append((ref, hyp))
        if len(samples) < 40:
            samples.append({"clip": e["clip"], "ref": ref, "hyp": hyp})
        # Live feedback: show the first 3 decodes immediately, then a running
        # counter every 10 clips (so it never looks frozen).
        if i < 3:
            msg(f"  [{i + 1}] ref: {ref[:60]}")
            msg(f"      hyp: {hyp[:60]}")
        elif (i + 1) % 10 == 0:
            msg(f"  {i + 1}/{len(rows)} — running WER {corpus_wer(pairs)['wer']:.1%}")

    result = corpus_wer(pairs)
    msg(f"\n==== {split} results ({result['n']} clips) ====")
    msg(f"  WER: {result['wer']:.1%}   ({result['word_edits']}/{result['words']} words)")
    msg(f"  CER: {result['cer']:.1%}   ({result['char_edits']}/{result['chars']} chars)")
    msg("  examples:")
    for s in samples[:8]:
        msg(f"    ref: {s['ref'][:70]}")
        msg(f"    hyp: {s['hyp'][:70]}\n")

    if samples_out:
        with open(samples_out, "w", encoding="utf-8") as f:
            json.dump({"result": result, "samples": samples}, f, ensure_ascii=False, indent=2)
        msg(f"wrote {samples_out}")
    return result


def _auto_device():
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate a Dutch VSR checkpoint (WER/CER).")
    ap.add_argument("--manifest", default="checkpoints/dutch/manifest.json")
    ap.add_argument("--checkpoint", default="checkpoints/dutch/dutch_vsr.pth")
    ap.add_argument("--auto-avsr-dir", default=None)
    ap.add_argument("--device", default=None)
    ap.add_argument("--split", default="test", choices=["test", "val", "train"])
    ap.add_argument("--limit", type=int, default=None, help="Only decode the first N clips.")
    ap.add_argument("--samples-out", default="checkpoints/dutch/eval_samples.json")
    args = ap.parse_args(argv)
    evaluate(args.manifest, args.checkpoint, auto_avsr_dir=args.auto_avsr_dir,
             device=args.device, split=args.split, limit=args.limit,
             samples_out=args.samples_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
