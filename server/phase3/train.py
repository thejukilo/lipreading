"""Train a Dutch VSR model by fine-tuning the English auto_avsr checkpoint.

Plan A (pilot): reuse the English tokenizer + model, fine-tune the whole network
on the Dutch clips. Optionally keep the visual encoder frozen for the first few
epochs (a warmup that lets the decoder adapt to Dutch before the encoder moves),
then unfreeze everything. Saves the best-by-val-loss checkpoint as a raw
state_dict that ``LipreadingEngine`` can load directly.

    python -m server.phase3.train --manifest checkpoints/dutch/manifest.json \
        --base checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth --epochs 40

Needs the user's CUDA GPU + the auto_avsr checkout (not runnable in CI).
"""

from __future__ import annotations

import argparse
import json
import os
import time


# Visual backbone prefixes (frontend 3D-conv/ResNet + Conformer encoder).
_ENCODER_PREFIXES = ("encoder.", "frontend.", "proj_encoder.")


def _set_encoder_frozen(model, frozen: bool) -> int:
    n = 0
    for name, p in model.named_parameters():
        if name.startswith(_ENCODER_PREFIXES):
            p.requires_grad_(not frozen)
            n += 1
    return n


def _run_epoch(model, loader, device, optim=None, scaler=None, amp_dtype=None,
               msg=None, tag=""):
    import time as _time

    import torch

    train = optim is not None
    model.train(train)
    total, steps = 0.0, 0
    n_batches = len(loader)
    amp = amp_dtype is not None
    dev_type = "cuda" if "cuda" in str(device) else "cpu"
    ctx = torch.enable_grad() if train else torch.no_grad()
    t0 = _time.perf_counter()
    with ctx:
        for bi, batch in enumerate(loader, 1):
            if batch is None:
                continue
            inputs = batch["inputs"].to(device)
            input_lengths = batch["input_lengths"].to(device)
            targets = batch["targets"].to(device)
            with torch.autocast(device_type=dev_type, dtype=amp_dtype, enabled=amp):
                loss = model(inputs, input_lengths, targets)[0]
            if train:
                optim.zero_grad(set_to_none=True)
                if scaler is not None and scaler.is_enabled():
                    scaler.scale(loss).backward()
                    scaler.unscale_(optim)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    scaler.step(optim)
                    scaler.update()
                else:
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optim.step()
            total += float(loss.detach())
            steps += 1
            if train and msg and bi % 200 == 0:
                el = _time.perf_counter() - t0
                eta = el / bi * (n_batches - bi)
                msg(f"  {tag}{bi}/{n_batches} — loss {total / steps:.1f} "
                    f"| {el / 60:.0f}m in, ~{eta / 60:.0f}m left")
    return total / max(steps, 1)


def _read_video_25fps(path):
    """Decode a raw webcam recording to (T,H,W,3) RGB, resampled to ~25 fps
    (the model's rate). Any container OpenCV can read works."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open probe video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
    cap.release()
    if not frames:
        raise RuntimeError("probe video has no frames")
    if abs(src_fps - 25.0) < 0.5:
        return np.asarray(frames, dtype=np.uint8)
    n_out = max(1, int(round(len(frames) * 25.0 / src_fps)))
    idx = [min(len(frames) - 1, int(round(i * src_fps / 25.0))) for i in range(n_out)]
    return np.asarray([frames[i] for i in idx], dtype=np.uint8)


def _prepare_probe(engine, path, msg):
    """Crop the probe video to 96x96 mouth ROIs once (deterministic); we re-decode
    it through the changing model each probe."""
    if engine.landmarks_detector is None:
        raise RuntimeError("probe needs the face detector")
    frames = _read_video_25fps(path)
    landmarks = engine.landmarks_detector(frames)
    crop = engine.video_process(frames, landmarks)
    if crop is None:
        raise RuntimeError("no face/mouth detected — face the camera, good light")
    msg(f"probe ready: {os.path.basename(path)} ({len(frames)} frames @25fps)")
    return crop


def train(manifest_path, base_ckpt, out_path="checkpoints/dutch/dutch_vsr.pth",
          auto_avsr_dir=None, detector="mediapipe", device=None,
          epochs=20, lr=1e-4, batch_size=4, freeze_encoder_epochs=3,
          num_workers=4, amp=True, probe_video=None, probe_every=2, on_progress=None):
    import torch

    from ..engine import LipreadingEngine
    from .data import PreparedClipDataset, collate_pad

    def msg(s):
        print(f"[train] {s}")
        if on_progress:
            on_progress(s)

    if device is None:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    data_dir = manifest["data_dir"]
    train_rows = [e for e in manifest["entries"] if e["split"] == "train"]
    val_rows = [e for e in manifest["entries"] if e["split"] == "val"]
    if not train_rows:
        raise RuntimeError("No training clips in manifest.")
    msg(f"train {len(train_rows)} clips | val {len(val_rows)} clips | device {device}")

    # The detector is only needed to crop a raw probe video (training clips are
    # already cropped), so only load mediapipe when a probe is requested.
    engine = LipreadingEngine(checkpoint_path=base_ckpt, auto_avsr_dir=auto_avsr_dir,
                              detector=detector, device=device,
                              load_detector=bool(probe_video))
    from datamodule.transforms import TextTransform, VideoTransform

    tt = TextTransform()
    train_ds = PreparedClipDataset(data_dir, train_rows, VideoTransform("train"), tt)
    val_ds = PreparedClipDataset(data_dir, val_rows, VideoTransform("test"), tt)
    train_loader = torch.utils.data.DataLoader(
        train_ds, batch_size=batch_size, shuffle=True, collate_fn=collate_pad,
        num_workers=num_workers, drop_last=True)
    val_loader = torch.utils.data.DataLoader(
        val_ds, batch_size=batch_size, shuffle=False, collate_fn=collate_pad,
        num_workers=num_workers) if val_rows else None

    model = engine.modelmodule.model
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    # Mixed precision: bf16 where the GPU supports it (stable, no loss scaler),
    # else fp16 with a GradScaler. Roughly halves memory and speeds the math —
    # the big lever once the encoder is unfrozen.
    amp_dtype, scaler = None, None
    if amp and "cuda" in str(device):
        if torch.cuda.is_bf16_supported():
            amp_dtype = torch.bfloat16
            msg("mixed precision: bf16")
        else:
            amp_dtype = torch.float16
            scaler = torch.cuda.amp.GradScaler()
            msg("mixed precision: fp16")

    # Optional "eyeball" probe: decode a clip of your own face every few epochs
    # so you can watch it start reading your lips (a realistic live-app preview).
    probe = None
    if probe_video:
        try:
            probe = _prepare_probe(engine, probe_video, msg)
        except Exception as e:
            msg(f"probe disabled: {e}")

    def run_probe(tag):
        if probe is None:
            return
        was_training = model.training
        model.eval()
        try:
            text = engine.transcribe_prepared_frames(probe)
            msg(f"👄 probe [{tag}]: “{text}”")
        except Exception as e:
            msg(f"probe failed: {e}")
        finally:
            model.train(was_training)

    run_probe("epoch 0 / untrained")

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    best_val = float("inf")
    encoder_frozen = None
    for epoch in range(1, epochs + 1):
        want_frozen = epoch <= freeze_encoder_epochs
        if want_frozen != encoder_frozen:
            n = _set_encoder_frozen(model, want_frozen)
            msg(f"encoder {'frozen' if want_frozen else 'unfrozen'} ({n} tensors)")
            encoder_frozen = want_frozen

        t0 = time.perf_counter()
        tr = _run_epoch(model, train_loader, device, optim, scaler, amp_dtype,
                        msg=msg, tag=f"e{epoch} ")
        dt = time.perf_counter() - t0
        line = f"epoch {epoch}/{epochs} — train {tr:.3f}"
        if val_loader is not None:
            vl = _run_epoch(model, val_loader, device, None, None, amp_dtype)
            line += f" | val {vl:.3f}"
            improved = vl < best_val
            if improved:
                best_val = vl
                model.eval()
                torch.save(model.state_dict(), out_path)
                line += "  ✓ saved (best)"
        else:
            model.eval()
            torch.save(model.state_dict(), out_path)
        msg(line + f"  [{dt:.0f}s]")

        if probe is not None and (epoch % probe_every == 0 or epoch == epochs):
            run_probe(f"epoch {epoch}")

    if val_loader is None:
        msg(f"saved final model: {out_path}")
    else:
        msg(f"best val loss {best_val:.3f} — saved {out_path}")
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fine-tune a Dutch VSR model (Plan A).")
    ap.add_argument("--manifest", default="checkpoints/dutch/manifest.json")
    ap.add_argument("--base", default=os.environ.get(
        "VSR_CHECKPOINT", "checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth"))
    ap.add_argument("--out", default="checkpoints/dutch/dutch_vsr.pth")
    ap.add_argument("--auto-avsr-dir", default=None)
    ap.add_argument("--device", default=None)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--freeze-encoder-epochs", type=int, default=3)
    ap.add_argument("--amp", dest="amp", action="store_true", default=True,
                    help="Mixed precision (default on; big speed/memory win on GPU).")
    ap.add_argument("--no-amp", dest="amp", action="store_false",
                    help="Disable mixed precision (use if you see NaN losses).")
    ap.add_argument("--probe-video", default=None,
                    help="A short webcam clip of you saying a Dutch sentence; it's "
                         "decoded every few epochs so you can watch it learn your lips.")
    ap.add_argument("--probe-every", type=int, default=2,
                    help="Run the probe every N epochs (default 2).")
    # Windows uses 'spawn', which pickles the dataset; auto_avsr's VideoTransform
    # holds a lambda that can't be pickled -> default to single-process there.
    ap.add_argument("--num-workers", type=int, default=(0 if os.name == "nt" else 4),
                    help="DataLoader workers (default 0 on Windows, 4 elsewhere).")
    args = ap.parse_args(argv)
    train(args.manifest, args.base, out_path=args.out, auto_avsr_dir=args.auto_avsr_dir,
          device=args.device, epochs=args.epochs, lr=args.lr, batch_size=args.batch_size,
          freeze_encoder_epochs=args.freeze_encoder_epochs, num_workers=args.num_workers,
          amp=args.amp, probe_video=args.probe_video, probe_every=args.probe_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
