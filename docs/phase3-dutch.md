# Phase 3 — a Dutch VSR model (pilot)

Goal: find out, with a hard number, what your **13.5 h of pre-cropped Dutch clips**
(5,577 clips, 156 source videos) can buy by fine-tuning the English auto_avsr
model. This is a self-contained train/eval pipeline, separate from the Phase-1
live app.

## Pilot result (first run)

Trained on 236 videos / 4,388 clips (10.7 h) with the frozen-warmup → unfreeze
schedule and bf16. Best model at **epoch 9** (val loss 79.5; it overfit after —
train loss kept falling while val rose, hence early stopping was added).

**Held-out test (32 unseen speaker-videos, 626 clips):**

| metric | value | reading |
|--------|-------|---------|
| **WER** | **66.7 %** | 1 in 3 words exactly right |
| **CER** | **38.8 %** | ~61 % of characters right — the truer gauge |

The WER↔CER gap means most errors are *near-misses* (a diacritic, a letter, a
homophene) rather than wild misses — exactly what the LLM cleanup layer repairs.
Example (unseen speaker): ref *"…daarom is het belangrijk dat zij die
flexibiliteit ook doortrekken"* → hyp *"Daarom is het belangrijk dat ik die
flexibiliteit ook doordel…"* — ~9 correct words in a row. It genuinely reads
Dutch lips. Some of the remaining WER is Plan-A tokenizer damage (`<unk>` on
Dutch diacritics, uppercase leakage) that Plan B removes for free.

**Takeaway:** validated recipe; data is the dominant lever from here (the
overfit signature = data-limited). Rough scaling: ~50 h → ~55–60 % WER, ~150 h →
~45–50 %. A speaker-dependent model (record yourself) reaches usable quality with
far less data and fits the app's personalization path.

## Why this can work at all

Lip-reading is very data-hungry (the English model saw ~1,400 h), so 13.5 h from
scratch would be hopeless. But we're not starting from scratch: the visual
encoder already turns a face into **visemes** (mouth shapes), which are largely
language-independent. We keep that and adapt the model to Dutch. Your clips are
also already in the model's **native format** (96×96, 25 fps, mouth-cropped), so
there's no preprocessing to get wrong.

**Honest expectation:** multi-speaker, open-domain Dutch at 13.5 h lands roughly
**60–75 % WER** — it'll get frequent words and short phrases, not clean
transcription. That's a real first Dutch lip-reader and a base that improves with
every added hour. The **Dutch LLM cleanup** layer (already built) on top makes a
noisy transcript far more usable, especially in a narrow domain.

## Plan A (this pilot) vs Plan B

- **Plan A — reuse the English tokenizer, fine-tune the whole model.** No vocab
  surgery, fastest path to a number, reuses the existing engine. Dutch is Latin
  script so it tokenizes fine (uppercased, matching the LRS3 vocab). The tokenizer
  is English-shaped, so this *understates* the ceiling — but it's the right first
  experiment. **This is what the scripts below do.**
- **Plan B — a dedicated Dutch SentencePiece tokenizer + a fresh decoder/CTC
  head.** Better ceiling, more work, needs your auto_avsr internals to wire up.
  Worth doing **only if Plan A looks promising.**

## Steps (on the CUDA machine)

Everything reads/writes under `checkpoints/dutch/`.

**1. Build the manifest + speaker-independent split.**
```powershell
python -m server.phase3.prepare --data-dir D:\path\to\dutch_clips
```
It pairs each `*.mp4` with its `*.txt`, groups clips by **source video** (the id
before the first `_`), and assigns whole videos to train/val/test so no speaker
leaks. Prints per-split clip/video/hours and writes `manifest.json`. Tune
`--val-frac` / `--test-frac` if you like.

**2. (Optional) Baseline — how bad is the untrained English model on Dutch?**
```powershell
python -m server.phase3.evaluate --checkpoint checkpoints\vsr_trlrs2lrs3vox2avsp_base.pth ^
    --split test --limit 100
```
Expect near-100 % WER. This is the "0 training" reference the fine-tuned model
should beat by a wide margin.

**3. Train.**
```powershell
python -m server.phase3.train --epochs 40 --batch-size 4
```
Loads the English checkpoint, keeps the visual encoder **frozen for the first few
epochs** (decoder adapts to Dutch first), then unfreezes everything. Saves the
best-by-val-loss model to `checkpoints\dutch\dutch_vsr.pth`. Data loading runs
single-process on Windows automatically (`--num-workers 0`), because auto_avsr's
transforms can't be pickled across Windows' spawned worker processes.

### Watch it learn *your* lips (optional probe)

Record a short webcam clip of yourself saying a Dutch sentence (phone or webcam,
face the camera, good light, ~2–5 s) and pass it with `--probe-video`:
```powershell
python -m server.phase3.train --epochs 20 --probe-video me_dutch.mp4 --probe-every 2
```
Every couple of epochs it decodes that clip through the current model and prints
what it "hears":
```
[train] 👄 probe [epoch 0 / untrained]: "these people can see the"   <- English nonsense
[train] 👄 probe [epoch 6]: "de mensen kunnen ..."                    <- Dutch emerging
```
It's the most satisfying progress signal — you literally watch it start reading
your mouth. Note this is your *raw* webcam through the mediapipe mouth-crop, so
it doubles as a realistic preview of live-app behaviour (and may read a little
worse than the test-split number if your crop differs from the dataset's).

**4. Evaluate — the honest number.**
```powershell
python -m server.phase3.evaluate --checkpoint checkpoints\dutch\dutch_vsr.pth
```
Decodes the held-out test videos and prints **WER + CER** plus example
`ref`/`hyp` pairs (also saved to `eval_samples.json`). Because these clips are
pre-cropped, evaluation uses the frames as-is — a clean measurement of the model.

## Reading the result

- **WER/CER dropping far below the baseline** → the model genuinely learned Dutch
  visemes→text; collecting more data is worth it, and Plan B (Dutch tokenizer)
  becomes the next lever.
- **Barely moving** → 13.5 h isn't enough for open-domain multi-speaker Dutch;
  options are much more data, or narrowing to a **speaker-dependent** model (train
  on one person) which needs far less.
- Look at the `hyp`/`ref` examples, not just the number — "phonetically close but
  wrong" is exactly what the LLM cleanup layer fixes.

## Using a Dutch model in the live app

Point **Recognition model** at `checkpoints/dutch/dutch_vsr.pth`. One caveat: the
live app crops the webcam with mediapipe→VideoProcess. If your training clips were
cropped with a **different alignment**, there's a train-vs-live mismatch to fix
before real-world use (align the app's crop to your data's, or reprocess). The
pilot's eval avoids this — it uses your already-cropped clips directly.

## Compute

13.5 h ≈ 1.2 M frames. Epoch time is very different before vs after the encoder
unfreezes: with the encoder **frozen** (epochs 1–3) an epoch is ~8 min; once
**unfrozen** the whole network trains and an epoch is much longer. **Mixed
precision is on by default** (`--amp`, bf16/fp16) to roughly halve memory and
speed the unfrozen epochs. During a long epoch you'll see intra-epoch progress
(`eN 200/1097 — loss … ~Nm left`) so it never looks frozen.

Default is `--epochs 20`, which is plenty for a pilot — the best-by-val
checkpoint is kept, so extra epochs never hurt quality, only time. If VRAM is
tight, drop `--batch-size` to 2. If you see NaN losses, add `--no-amp`.
