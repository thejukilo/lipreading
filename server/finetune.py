"""Light fine-tuning of the VSR model on the user's own clips (Teach → Train).

Adapts the base auto_avsr checkpoint to *your* face and vocabulary using the
clips collected in the Teach tab, and saves a SEPARATE ``personalized.pth`` —
the base model is never touched.

Design for safety on tiny datasets:
- very low learning rate + few epochs (nudge, don't overwrite),
- gradient clipping,
- reuses the exact mouth-crop + transforms + collate + model-forward that
  auto_avsr trains with, so this mirrors their working training path.

Can't be unit-tested here (needs torch + CUDA + the checkpoint); it's built to
match auto_avsr's own train loop and run on the user's GPU.
"""

from __future__ import annotations

import os


# --- auto_avsr's collate, copied verbatim so batch shapes match their model ---

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


def _collate_pad(batch):
    import torch

    out = {}
    for key in batch[0].keys():
        pad_val = -1 if key == "target" else 0.0
        c, lens = _pad([s[key] for s in batch if s[key] is not None], pad_val)
        out[key + "s"] = c
        out[key + "_lengths"] = torch.tensor(lens)
    return out


class _ClipDataset:
    """Mouth-crops each clip once (cached), applies the train VideoTransform and
    tokenizes the label per __getitem__ so augmentation varies across epochs."""

    def __init__(self, store, engine, video_transform, text_transform, on_msg=None):
        import torch

        self._torch = torch
        self.video_transform = video_transform
        self.text_transform = text_transform
        self.samples = []  # (cropped_frames_tensor, token_ids)

        entries = store._load()
        for i, e in enumerate(entries):
            if on_msg:
                on_msg(f"preparing clip {i + 1}/{len(entries)}: “{e['phrase']}”")
            frames = store.load_clip(e["clip"])          # (T,H,W,3) RGB
            landmarks = engine.landmarks_detector(frames)
            crop = engine.video_process(frames, landmarks)  # (T,96,96,3)
            if crop is None:
                if on_msg:
                    on_msg(f"skipped “{e['phrase']}” (no face detected)")
                continue
            vid = torch.tensor(crop).permute(0, 3, 1, 2)   # (T,3,96,96)
            # auto_avsr's tokenizer/model vocabulary is UPPERCASE (LRS3). Lowercase
            # labels tokenize to <unk> — so the model would learn to output <unk>.
            tokens = text_transform.tokenize(e["phrase"].upper())
            unk = text_transform.hashmap.get("<unk>")
            if unk is not None and len(tokens) and all(int(t) == int(unk) for t in tokens):
                if on_msg:
                    on_msg(f"skipped “{e['phrase']}” (no known tokens)")
                continue
            self.samples.append((vid, tokens))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        vid, tokens = self.samples[idx]
        return {"input": self.video_transform(vid), "target": tokens}


def finetune(
    store,
    checkpoint_path: str,
    out_path: str = "checkpoints/personalized.pth",
    auto_avsr_dir: str | None = None,
    detector: str = "mediapipe",
    device: str | None = None,
    epochs: int = 15,
    lr: float = 5e-5,
    batch_size: int = 2,
    on_progress=None,
) -> str:
    """Fine-tune and save a personalized checkpoint. Returns its path."""
    import torch

    from .engine import LipreadingEngine

    def msg(s):
        print(f"[finetune] {s}")
        if on_progress:
            on_progress(s)

    if device is None:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"

    n_clips, n_phrases = store.stats()
    if n_clips < 4:
        raise RuntimeError(
            f"Only {n_clips} clip(s) collected — record more first "
            "(aim for several phrases with multiple reps each)."
        )
    msg(f"loading base model on {device}…")
    engine = LipreadingEngine(checkpoint_path=checkpoint_path,
                              auto_avsr_dir=auto_avsr_dir, detector=detector, device=device)

    from datamodule.transforms import TextTransform, VideoTransform

    ds = _ClipDataset(store, engine, VideoTransform("train"), TextTransform(), on_msg=msg)
    if len(ds) < 4:
        raise RuntimeError("Too few usable clips after mouth-crop — check framing/lighting.")

    loader = torch.utils.data.DataLoader(
        ds, batch_size=batch_size, shuffle=True, collate_fn=_collate_pad, num_workers=0
    )
    model = engine.modelmodule.model
    model.train()
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    msg(f"training: {len(ds)} clips, {n_phrases} phrases, {epochs} epochs, lr={lr}")
    for epoch in range(epochs):
        total, steps = 0.0, 0
        for batch in loader:
            inputs = batch["inputs"].to(device)
            input_lengths = batch["input_lengths"].to(device)
            targets = batch["targets"].to(device)
            loss = model(inputs, input_lengths, targets)[0]
            optim.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            total += float(loss.detach())
            steps += 1
        msg(f"epoch {epoch + 1}/{epochs} — loss {total / max(steps, 1):.3f}")

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    model.eval()
    # Save a raw state_dict — the same format LipreadingEngine loads.
    torch.save(model.state_dict(), out_path)
    msg(f"saved personalized model: {out_path}")
    return out_path
