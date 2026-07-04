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


def _run_epoch(model, loader, device, optim=None):
    import torch

    train = optim is not None
    model.train(train)
    total, steps = 0.0, 0
    ctx = torch.enable_grad() if train else torch.no_grad()
    with ctx:
        for batch in loader:
            if batch is None:
                continue
            inputs = batch["inputs"].to(device)
            input_lengths = batch["input_lengths"].to(device)
            targets = batch["targets"].to(device)
            loss = model(inputs, input_lengths, targets)[0]
            if train:
                optim.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optim.step()
            total += float(loss.detach())
            steps += 1
    return total / max(steps, 1)


def train(manifest_path, base_ckpt, out_path="checkpoints/dutch/dutch_vsr.pth",
          auto_avsr_dir=None, detector="mediapipe", device=None,
          epochs=40, lr=1e-4, batch_size=4, freeze_encoder_epochs=3,
          num_workers=4, on_progress=None):
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

    engine = LipreadingEngine(checkpoint_path=base_ckpt, auto_avsr_dir=auto_avsr_dir,
                              detector=detector, device=device, load_detector=False)
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
        tr = _run_epoch(model, train_loader, device, optim)
        dt = time.perf_counter() - t0
        line = f"epoch {epoch}/{epochs} — train {tr:.3f}"
        if val_loader is not None:
            vl = _run_epoch(model, val_loader, device, None)
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
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--freeze-encoder-epochs", type=int, default=3)
    # Windows uses 'spawn', which pickles the dataset; auto_avsr's VideoTransform
    # holds a lambda that can't be pickled -> default to single-process there.
    ap.add_argument("--num-workers", type=int, default=(0 if os.name == "nt" else 4),
                    help="DataLoader workers (default 0 on Windows, 4 elsewhere).")
    args = ap.parse_args(argv)
    train(args.manifest, args.base, out_path=args.out, auto_avsr_dir=args.auto_avsr_dir,
          device=args.device, epochs=args.epochs, lr=args.lr, batch_size=args.batch_size,
          freeze_encoder_epochs=args.freeze_encoder_epochs, num_workers=args.num_workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
