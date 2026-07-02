# Step 2–4 — Live push-to-talk into Google Meet

Mouth a sentence at your webcam → the model transcribes it → it's spoken in a
TTS voice → played into a **virtual microphone** so Google Meet hears it as you.

```
hold key + mouth  ─►  webcam @25fps  ─►  VSR model  ─►  transcript
                                                            │ (review / auto)
Google Meet  ◄── mic: "CABLE Output" ◄── VB-Cable ◄── play ◄── Piper TTS
```

## One-time setup

**1. Install VB-Cable (the virtual microphone).**
Download from https://vb-audio.com/Cable/, unzip, right-click the installer →
Run as administrator, then reboot. Afterwards Windows has two new devices:
- **CABLE Input** — a *playback* device (our app plays TTS here)
- **CABLE Output** — a *recording* device (Meet uses this as the mic)

**2. Python deps + models** (from the repo root, in your venv):
```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```
The setup script downloads the Piper voice (`en_US-lessac-medium`) into
`models\piper\` alongside the VSR checkpoint and face detector.

**3. Point Google Meet at the virtual mic.**
In Meet: ⚙ Settings → Audio → **Microphone** → **CABLE Output (VB-Audio Virtual
Cable)**. Leave Speakers as your normal headphones/speakers.

> Test the mic: Meet's settings show an input level meter — run the app, speak
> one utterance, and watch it move.

## Run it

```powershell
python -m server.live_app
```
On start it loads the model (a moment), opens a webcam preview window, and arms
the push-to-talk key.

### Controls
- **Hold RIGHT CTRL** and mouth a sentence; **release** to end. (Change with
  `--key`, e.g. `--key f8` or `--key space`.)
- **Review mode (default):** focus the preview window, then
  **Enter** = speak into Meet · **Esc** = discard · **e** = edit text in the terminal.
- **Q** in the window quits.

The push-to-talk key is **global** — it works while you're focused on the Meet
tab. The review keys are read from the app window, so to confirm you alt-tab to
it briefly. If you'd rather stay hands-free in Meet, use auto-speak:

```powershell
python -m server.live_app --auto-speak
```
(Release → speaks immediately, no confirm. Fastest, but a misread goes out loud.)

## Hearing what's being said

Two things to know:

1. **Meet never plays your own microphone back to you** — that's normal anti-echo
   behavior. Even when it's working, *you* won't hear it in the call; the other
   participants will. To truly verify what others hear, **join the same meeting
   from a phone/second device** as another participant.
2. **Local monitor (on by default):** the app also plays the synthesized audio to
   your **speakers/headphones** so you hear exactly what was sent to Meet. Turn it
   off with `--no-monitor`; choose a specific output with
   `--monitor-device "Headphones"` (or an index from `--list-audio-devices`).

So: the mic level moving in Meet = it's working. The monitor lets you hear it;
a second participant confirms others hear it too.

## Options

| Flag | Default | Notes |
|------|---------|-------|
| `--key` | `ctrl_r` | Push-to-talk key: a letter, or `ctrl_r/ctrl_l/alt_r/space/f7..f10`. |
| `--tts` | `piper` | `piper` (local, natural) or `sapi` (Windows built-in, robotic, no download). |
| `--output-device` | `CABLE Input` | Playback device name substring or index. |
| `--auto-speak` | off | Skip review; speak on release. |
| `--no-monitor` | off | Stop also playing to your speakers (monitor is on by default). |
| `--monitor-device` | default output | Which speakers/headphones hear the monitor. |
| `--camera` | `0` | Webcam index if you have several. |
| `--list-audio-devices` | — | Print playback device names/indices and exit. |
| `--device` | auto | `cuda:0` or `cpu`. |

## Camera contention (if you're also on-camera in Meet)

Windows often lets only one app own the webcam. If Meet already has the camera,
this app can't open it (and vice-versa). Options:
- Phase 1 simplest: stay **off-camera** in Meet while using the app.
- Or install **OBS**, add your webcam as a source, start **Virtual Camera**, and
  select "OBS Virtual Camera" in Meet — then point this app at your real webcam
  (`--camera`). Both get a feed.

## Troubleshooting

- **No audio reaches Meet** — confirm Meet's mic is **CABLE Output** (not Input),
  and the app's `--output-device` is **CABLE Input**. `--list-audio-devices`
  shows exact names; VB-Cable device names must be present.
- **`piper executable not found`** — `pip install piper-tts` put a `piper` on
  PATH inside the venv; make sure the venv is active, or use `--tts sapi`.
- **Camera won't open** — another app (Meet!) owns it; see camera contention.
  Try a different `--camera` index.
- **Push-to-talk does nothing** — some security tools block global key hooks; try
  running the terminal as administrator, or pick a different `--key`.
- **Transcript worse than the demo clip** — framing/lighting/rate. Face the
  camera head-on, well lit; the app already samples at 25 fps to match training.
- **`too short to read`** — hold the key a bit longer (need ≥ ~0.3 s of mouthing).

## What's next (step 5)

The Chrome extension: an in-Meet overlay showing push-to-talk state + the live
transcript with a confirm/edit box, talking to this app over a localhost API.
The audio path (VB-Cable) stays exactly the same — the extension just replaces
the webcam preview window as the control surface.
