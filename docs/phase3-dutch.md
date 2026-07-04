# Phase 3 — a Dutch VSR model (pilot)

Goal: find out, with a hard number, what your **13.5 h of pre-cropped Dutch clips**
(5,577 clips, 156 source videos) can buy by fine-tuning the English auto_avsr
model. This is a self-contained train/eval pipeline, separate from the Phase-1
live app.

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

13.5 h ≈ 1.2 M frames. On a single modern CUDA GPU, an epoch is minutes and a
40-epoch run is a few hours — not days. Start with a short run (`--epochs 5`) to
confirm the loss drops, then do the full run.
