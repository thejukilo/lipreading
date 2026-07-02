# Phase 1 — Design

Windows + NVIDIA CUDA. Push-to-talk. Prebuilt voice. Local inference.
Goal of the first milestone: an **end-to-end thin slice** that proves the whole
pipe, with rough accuracy.

## Pipeline

```
                        ┌─────────────────────── local machine (Windows) ───────────────────────┐
webcam ──► capture ──► lip crop ──► [push-to-talk buffer] ──► VSR model ──► text
                                                                              │
                                                                              ▼
Google Meet ◄── virtual mic (VB-Cable) ◄── PCM ◄── TTS (prebuilt voice) ◄────┘
     ▲
     └── Chrome extension = thin controller/UI (talks to localhost, shows
         transcript + edit/confirm box, drives push-to-talk)
```

## Components

### 1. Inference server (Python, `localhost`)
- Wraps **auto_avsr** (chosen over AV-HuBERT for Phase 1: active repo, clean
  Conformer VSR checkpoints, simpler inference, strong English LRS3 WER).
- Exposes a tiny local API — WebSocket preferred (push frames / stream partials)
  with an HTTP fallback for the batch "transcribe this clip" call.
- CUDA PyTorch. Loads the pretrained English VSR checkpoint once.

### 2. Capture + lip crop
- Grab webcam frames (OpenCV / MediaPipe).
- Face detect + landmark → mouth ROI, resized to the model's expected input
  (auto_avsr: 96×96 grayscale mouth crop). This preprocessing is required — the
  model does not take raw frames.
- Push-to-talk: buffer frames between key-down and key-up into one utterance.

### 3. TTS + virtual-mic bridge
- Phase 1 voice: **Piper** (local, low-latency, offline) as default; ElevenLabs
  as an optional higher-quality/cloud swap. Interface kept pluggable so Phase 2
  voice cloning drops in behind the same boundary.
- Write synthesized PCM into **VB-Audio Virtual Cable**; Meet selects
  "CABLE Output" as its microphone.

### 4. Chrome extension
- Thin controller. Connects to the local server over `localhost`.
- UI: push-to-talk state, live/partial transcript, an **edit + confirm** box
  (safety net for recognition errors) and a Speak button.
- Does **not** run the model and does **not** touch Meet's captured mic stream.

## Known constraints to design around

- **Camera contention:** if on-camera in Meet, use OBS virtual camera to fan the
  webcam to both apps; otherwise stay off-camera in Phase 1.
- **Latency:** mouth-to-voice > ~1–2 s feels broken. Push-to-talk (clean
  segment boundaries) sidesteps the streaming/endpointing problem for now.
- **Localhost bridge trust:** extension ↔ server needs a stable local port and a
  simple handshake so arbitrary pages can't drive the mic.

## First vertical slice (thin, end-to-end)

Order that keeps every step demoable:

1. ✅ **Model smoke test** — load auto_avsr English checkpoint, transcribe a
   pre-recorded lip clip from disk. Confirms CUDA + weights + preprocessing.
   (`server/engine.py`, verified — transcripts spot-on with the 20.3% WER model.)
2. ✅ **Capture → transcript** — webcam + push-to-talk (25 fps) → lip crop →
   transcript. (`server/live_app.py`)
3. ✅ **Text → virtual mic** — Piper/SAPI TTS → VB-Cable → heard as the mic.
   (`server/tts.py`, `server/audio_out.py`)
4. ✅ **Join the halves** — the live app runs 2→3→4 as one push-to-talk loop
   with a review/confirm step. *Pending on-device testing on Windows.*
5. ⏳ **Extension shell** — Chrome extension that shows push-to-talk state +
   transcript + edit/confirm, driving the local app over localhost. Demo in Meet.

## Open items (not blocking the slice)

- Exact auto_avsr checkpoint + its preprocessing dependency versions on Windows.
- WebSocket message schema (frame push vs. clip upload).
- How much of lip-crop preprocessing to keep in Python vs. move client-side later.
- Local-bridge auth/handshake details.

## Later phases (recorded, not built yet)

- **Phase 2:** wizard to record the user and fine-tune/clone their voice; swap it
  in behind the TTS boundary. Still English VSR.
- **Phase 3:** custom Dutch VSR model — parked pending Dutch data collection
  (LRS-style: video + aligned transcripts).
