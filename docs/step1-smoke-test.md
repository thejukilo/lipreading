# Step 1 — Model smoke test

Goal: prove CUDA + auto_avsr weights + mouth-crop preprocessing all work by
transcribing a **pre-recorded** video clip from disk. No webcam, no audio, no
extension yet. This de-risks the hardest external dependency before we build
anything on top of it.

## What this validates

- The auto_avsr Conformer VSR checkpoint loads and runs on your GPU.
- The mouth-cropping detector (mediapipe) finds a face and produces the 96×96
  ROI the model expects.
- The ESPnet beam-search decoder + sentencepiece tokenizer return real text.

## Prerequisites

- Windows, NVIDIA GPU with a recent driver, `git` on PATH.
- Python 3.10 recommended (matches auto_avsr's tested range).

## One-time setup

```powershell
# 1. Python env + CUDA torch (choose the CUDA build that matches your driver)
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt

# 2. Clone auto_avsr + download checkpoint + demo clip
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

This lays down:

```
third_party/auto_avsr/                    # model code, tokenizer, vendored espnet
checkpoints/vsr_trlrs3_base.pth           # English VSR base checkpoint (LRS3)
models/blaze_face_short_range.tflite      # mediapipe Tasks face detector
media/demo.mp4                            # auto_avsr's demo clip
```

> **Note on the face detector.** auto_avsr's bundled mediapipe detector uses the
> old `mp.solutions` API, which Google **removed** in mediapipe ≥ ~0.10.18 (on
> current mediapipe you'd hit `module 'mediapipe' has no attribute 'solutions'`).
> We replace it with a Tasks-API detector (`server/detectors.py`) that produces
> the identical landmark format, so any modern mediapipe works — no downgrade,
> no pinned Python needed. It uses the BlazeFace model downloaded above (override
> its path with `BLAZE_FACE_MODEL`).

## Run it

```powershell
python -m server.engine --video media\demo.mp4 --checkpoint checkpoints\vsr_trlrs3_base.pth
```

Expected: a `===== TRANSCRIPT =====` block with the spoken text, plus load and
inference timings. On the demo clip the base model should produce readable
English (it won't be perfect — that's fine for step 1).

## Options

| Flag | Default | Notes |
|------|---------|-------|
| `--device` | auto (`cuda:0` if available) | Force `cpu` to sanity-check without GPU. |
| `--detector` | `mediapipe` | `mediapipe` is easiest to install on Windows. `retinaface` needs the ibug packages but can be more robust. |
| `--auto-avsr-dir` | `$AUTO_AVSR_DIR` or `third_party/auto_avsr` | Point at a different checkout. |
| `--checkpoint` | `checkpoints/vsr_trlrs3_base.pth` | Try `vsr_trlrs2lrs3vox2avsp_base.pth` (WER 20.3) for better accuracy. |

## Troubleshooting

- **`No face/landmarks detected`** — the clip must show a front-facing mouth
  with decent lighting. Try a clearer clip.
- **CPU-only torch installed** — reinstall torch from the `cu121` index *before*
  `requirements.txt`, or pip will keep the CPU wheel.
- **`auto_avsr checkout not found`** — run `scripts\setup_windows.ps1`, or set
  `AUTO_AVSR_DIR` to your checkout.
- **`module 'mediapipe' has no attribute 'solutions'`** — expected on modern
  mediapipe; our Tasks-API detector avoids it. If you still see it, you're on an
  old checkout that imports auto_avsr's detector — pull latest.
- **`BlazeFace model not found`** — run the setup script, or set
  `BLAZE_FACE_MODEL` to the `.tflite` path.

## Next (step 2)

Once this prints a sensible transcript, we swap the file input for a **webcam +
push-to-talk** capture that buffers one utterance and feeds the same
`LipreadingEngine.transcribe(...)` path.
