# Lipreading → Voice

Silent-speech interface: a user "speaks" without making sound, the system
lipreads from the webcam, transcribes it, converts it to speech in a chosen
voice, and plays that audio into a meeting **as if the user were talking**.

Built on prior visual-speech-recognition (VSR) work — primarily
[auto_avsr](https://github.com/mpc001/auto_avsr) and
[AV-HuBERT](https://github.com/facebookresearch/av_hubert).

## Why this is mostly a plumbing problem

The lipreading model is the well-trodden part. The hard/novel engineering is
everything around it:

- A **Chrome extension cannot** run a PyTorch VSR model or spoof the microphone
  stream Meet captures. It is a thin controller/UI only.
- Getting audio into Google Meet "as you" requires a **virtual microphone** at
  the OS level. Meet just records whatever mic device is selected.
- `auto_avsr` / AV-HuBERT are built for **offline, pre-segmented, lip-cropped
  clips** — not live streaming. Real-time streaming VSR is a later delta.
- If the user is also on-camera in Meet, **both apps want the webcam**. Needs a
  camera splitter (OBS virtual cam) or the user stays off-camera in Phase 1.

## Phases

| Phase | Goal | Status |
|-------|------|--------|
| **1** | English pretrained model + app + Chrome extension. Push-to-talk lipreading → prebuilt TTS voice → virtual mic → Google Meet. | In definition |
| **2** | Still English. In-app wizard to **clone the user's own voice** (record or upload) and speak in it (XTTS v2). | In progress |
| **3** | Custom **Dutch** VSR model. Parked pending Dutch data collection. | Parked |

## Phase 1 decisions (locked)

- **Inference:** local first (Python server on the user's machine), cloud later.
- **Interaction:** push-to-talk (hold key → mouth an utterance → release → speak).
- **Voice:** prebuilt/stock TTS voice first (cloning is Phase 2).
- **Platform:** Windows, single-OS dev-grade setup.
- **Hardware:** NVIDIA CUDA GPU.
- **First slice:** end-to-end thin — prove the whole pipe, accuracy rough.

See [`docs/phase1-design.md`](docs/phase1-design.md) for the architecture and the
vertical-slice build plan.

## Getting started

Common setup (Windows + CUDA):
```powershell
py -3.10 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1   # models + Piper voice
```

**Step 1 — model smoke test** (transcribe a recorded clip; proves the pipeline):
```powershell
python -m server.engine --video media\demo.mp4 --checkpoint checkpoints\vsr_trlrs2lrs3vox2avsp_base.pth
```
→ [`docs/step1-smoke-test.md`](docs/step1-smoke-test.md)

**Step 2–4 — live push-to-talk into Google Meet** (webcam → transcript → voice
→ virtual mic). Needs VB-Cable installed; select **CABLE Output** as Meet's mic.

Desktop app (recommended — no terminal): **double-click `run.bat`**, or
```powershell
python -m server.gui_app           # pick devices, Start, hold to talk
```
→ [`docs/desktop-ui.md`](docs/desktop-ui.md)

Terminal front-end (same engine):
```powershell
python -m server.live_app          # hold RIGHT CTRL, mouth a sentence, review, speak
```
→ [`docs/step2-live-meet.md`](docs/step2-live-meet.md)

**Voice cloning (Phase 2)** — clone your own voice from a short recorded/uploaded
clip and speak in it. In the app: **Voice → ＋ Clone**. Optional install:
```powershell
pip install -r requirements-voice.txt
```
→ [`docs/voice-cloning.md`](docs/voice-cloning.md)

**Text cleanup (LLM)** — fix lipreading homophone errors (god→dog, beating→
meeting) with a language model. In the app: **Text cleanup** → Local (Ollama) or
Claude. Optional install for the Claude backend:
```powershell
pip install -r requirements-llm.txt
```
→ [`docs/text-cleanup.md`](docs/text-cleanup.md)

**Teach / personalize (in progress)** — collect clips of yourself saying your own
words (names, jargon) to later fine-tune a **Personalized** model. In the app:
the **Teach** tab, or **＋ Add to training** when you fix a wrong transcript.
→ [`docs/teaching.md`](docs/teaching.md)
