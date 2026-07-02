# Voice cloning (Phase 2)

Make the spoken output sound like **your** voice. You give the app a short
reference clip (record it in-app or upload a WAV); it clones your voice with
**Coqui XTTS v2** — zero-shot, no training — and uses it for everything you
"say" in Meet.

## One-time install

Voice cloning is an optional add-on (kept separate so it can't disturb your
CUDA-torch setup):
```powershell
pip install -r requirements-voice.txt
```
The first time you actually use a cloned voice, XTTS downloads its ~1.8GB model
to your TTS cache (once). A CUDA GPU makes synthesis fast; CPU works but is slow.

> **License:** the XTTS v2 model is under the Coqui Public Model License (CPML),
> which is **non-commercial**. Fine for personal use and development. If this
> becomes a product, swap the clone engine (e.g. OpenVoice v2 = MIT, or
> ElevenLabs' commercial cloning API) — it lives behind the same interface, so
> it's a contained change.

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

Select it in the dropdown, then **Stop → Start** to apply it. From then on,
everything you mouth is spoken in your voice.

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
