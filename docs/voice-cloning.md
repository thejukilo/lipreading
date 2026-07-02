# Voice cloning (Phase 2)

Make the spoken output sound like **your** voice. You give the app a short
reference clip (record it in-app or upload a WAV); it clones your voice —
zero-shot, no training — and uses it for everything you "say" in Meet.

Two engines are available (pick under **Cloning engine**):
- **VoxCPM** (default) — tokenizer-free, more natural/expressive. Needs torch ≥ 2.5.
- **XTTS** (Coqui) — the earlier option; non-commercial model license.

## One-time install

Voice cloning is an optional add-on (kept separate so it can't disturb your
CUDA-torch setup):
```powershell
pip install -r requirements-voice.txt
```

**VoxCPM needs torch ≥ 2.5 and CUDA ≥ 12.** Check yours:
```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
If it's older than 2.5, upgrade with the CUDA wheel (keeps GPU support):
```powershell
pip install -U torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```
The first time you use a cloned voice, the model downloads once (a GB or two).
A CUDA GPU makes synthesis fast; CPU is slow.

> **Best-quality cloning:** when you **record** in-app you read a known passage,
> so the app feeds VoxCPM that transcript automatically ("ultimate cloning").
> Uploaded clips clone from audio only (still good, slightly less similar).

> **Licenses:** VoxCPM — check the OpenBMB model card for terms. XTTS v2 — Coqui
> Public Model License (CPML), **non-commercial**. Both fine for personal use;
> for a product, confirm terms or use a commercially-licensed engine (the TTS
> layer is pluggable, so swapping is contained).

## Clone a voice (in the app)

1. In the desktop app, next to **Voice**, click **＋ Clone**.
2. Give the voice a **name**.
3. Provide a reference clip, either:
   - **Record** — read the on-screen passage aloud (aim for 15–30s of clear
     speech in a quiet room), then **Stop**. Use **Play back** to check it.
   - **Upload a file** — choose a **WAV** file of clean speech.
4. (Optional) **Preview voice** — synthesizes a test line in the cloned voice and
   plays it on your speakers. The first preview loads the model, so it's slow;
   later ones are quick.
5. **Save**. The voice appears in the **Voice** dropdown as "🗣 <name> (your voice)".

Select it in the dropdown, choose your **Cloning engine** (VoxCPM by default),
then **Stop → Start** to apply it. From then on, everything you mouth is spoken
in your voice. Switching the cloning engine also needs a Stop → Start.

Voices are stored under `~/.lipreading/voices/<slug>/reference.wav`. Delete one
with the **Delete** button next to the Voice dropdown.

## Tips for a good clone

- 15–30 seconds is the sweet spot; more isn't necessarily better.
- Quiet room, consistent distance from the mic, natural pace.
- One speaker only, no background music/noise.
- WAV uploads only for now (mp3/m4a aren't decoded — record in-app or convert to
  WAV first).

## Latency note

XTTS synthesis takes ~1–3s per sentence on a GPU. With the review step that's
fine; with **Speak immediately** mode it adds a beat before your voice plays.
Piper (the default voice) is faster if you want minimal delay.

## Command line

The terminal front-end can use a cloned voice too:
```powershell
python -m server.live_app --voice clone:<slug>
```
(`<slug>` is the folder name under `~/.lipreading/voices/`.)
