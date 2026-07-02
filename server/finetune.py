"""Light fine-tuning of the VSR model on the user's own clips (Teach → Train).

Adapts the base auto_avsr checkpoint to *your* face and vocabulary using the
clips collected in the Teach tab, and saves a SEPARATE ``personalized.pth`` —
the base model is never touched.

Why this is careful (avoiding "it only says the words I taught it")
-------------------------------------------------------------------
Fine-tuning a big sequence-to-sequence model on a handful of clips of a few
phrases is a classic recipe for **catastrophic forgetting**: the autoregressive
decoder memorizes those exact sentences and starts emitting them no matter what
the camera shows. A naive full fine-tune on ~18 clips of 3 phrases collapses
onto exactly those 3 phrases.

We fight that on three fronts, all on by default:

1. **Freeze the visual backbone.** The 3D-conv/ResNet frontend and the whole
   Conformer encoder — the general, hard-won viseme extractor — are frozen. We
   only train the decoder + CTC head, i.e. the *mapping from visemes to your
   words*. The encoder can't be damaged, so general lip-reading survives.
2. **L2-SP anchor.** Every trainable weight is penalized for drifting away from
   its base value (``lambda * ||theta - theta_base||^2``). This keeps the
   decoder's language behaviour close to the original instead of collapsing onto
   the tiny training set.
3. **Gentle schedule + early stop.** Low learning rate, few epochs, gradient
   clipping, and a memorization guard that stops as soon as the loss floors out
   (a sign the model is starting to memorize rather than adapt).

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


# --- freezing --------------------------------------------------------------

# Parameters whose name starts with any of these prefixes are the general
# visual backbone (frontend 3D-conv/ResNet + Conformer encoder). We freeze
# them so personalization can't damage general lip-reading; only the decoder
# and CTC head (viseme -> your words) are trained.
_FREEZE_PREFIXES = ("encoder.", "frontend.", "proj_encoder.")


def _split_params(model, freeze_backbone: bool):
    """Return (trainable_named_params, n_frozen). Freezes the visual backbone.

    Falls back to training everything if the expected module names aren't found,
    so a future auto_avsr refactor degrades to the old behaviour rather than
    silently training nothing.
    """
    named = list(model.named_parameters())
    if not freeze_backbone:
        return named, 0
    frozen = 0
    trainable = []
    for name, p in named:
        if name.startswith(_FREEZE_PREFIXES):
            p.requires_grad_(False)
            frozen += 1
        else:
            p.requires_grad_(True)
            trainable.append((name, p))
    if not trainable:  # names didn't match — don't train a frozen model
        for _, p in named:
            p.requires_grad_(True)
        return named, 0
    return trainable, frozen


def finetune(
    store,
    checkpoint_path: str,
    out_path: str = "checkpoints/personalized.pth",
    auto_avsr_dir: str | None = None,
    detector: str = "mediapipe",
    device: str | None = None,
    epochs: int = 6,
    lr: float = 1e-4,
    batch_size: int = 2,
    freeze_backbone: bool = True,
    l2sp: float = 1e-2,
    early_stop_loss: float = 0.08,
    on_progress=None,
) -> str:
    """Fine-tune and save a personalized checkpoint. Returns its path.

    Parameters worth knowing:
    - ``freeze_backbone``: freeze the visual frontend + Conformer encoder and
      train only the decoder + CTC head (default True; the main defence against
      forgetting).
    - ``l2sp``: strength of the anchor pulling trainable weights back toward the
      base model (0 disables it).
    - ``early_stop_loss``: stop once the epoch loss drops below this — going
      lower means the model is memorizing the tiny training set.
    """
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
    if n_phrases < 2:
        msg("⚠ only one distinct phrase — the model may over-focus on it; "
            "add more varied phrases/sentences for a balanced result.")

    loader = torch.utils.data.DataLoader(
        ds, batch_size=batch_size, shuffle=True, collate_fn=_collate_pad, num_workers=0
    )
    model = engine.modelmodule.model
    model.train()

    trainable, n_frozen = _split_params(model, freeze_backbone)
    if freeze_backbone:
        msg(f"froze {n_frozen} backbone tensors; training {len(trainable)} "
            "decoder/CTC tensors (visual encoder is preserved)")

    # L2-SP anchor: snapshot the base values of the trainable weights so we can
    # penalize drift away from them. Detached clones on-device, no grad.
    anchors = None
    if l2sp > 0:
        anchors = [(p, p.detach().clone()) for _, p in trainable]

    params = [p for _, p in trainable]
    optim = torch.optim.AdamW(params, lr=lr, weight_decay=1e-4)

    msg(f"training: {len(ds)} clips, {n_phrases} phrases, up to {epochs} epochs, "
        f"lr={lr}, l2sp={l2sp}, freeze_backbone={freeze_backbone}")
    for epoch in range(epochs):
        total, reg_total, steps = 0.0, 0.0, 0
        for batch in loader:
            inputs = batch["inputs"].to(device)
            input_lengths = batch["input_lengths"].to(device)
            targets = batch["targets"].to(device)
            loss = model(inputs, input_lengths, targets)[0]

            reg = inputs.new_zeros(())
            if anchors is not None:
                for p, p0 in anchors:
                    reg = reg + ((p - p0) ** 2).sum()
                loss = loss + l2sp * reg

            optim.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optim.step()
            total += float(loss.detach())
            reg_total += float(reg.detach()) if anchors is not None else 0.0
            steps += 1
        avg = total / max(steps, 1)
        msg(f"epoch {epoch + 1}/{epochs} — loss {avg:.3f}"
            + (f" (drift {reg_total / max(steps, 1):.3f})" if anchors is not None else ""))
        # Memorization guard: once the loss floors out we're fitting the tiny set
        # rather than adapting — stop before general recognition erodes.
        if avg < early_stop_loss:
            msg(f"early stop — loss below {early_stop_loss} (avoids over-memorizing)")
            break

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    model.eval()
    # Save a raw state_dict — the same format LipreadingEngine loads. The frozen
    # backbone tensors are identical to the base checkpoint, so this is a full,
    # self-contained model (just with an adapted decoder/CTC head).
    torch.save(model.state_dict(), out_path)
    msg(f"saved personalized model: {out_path}")
    return out_path
