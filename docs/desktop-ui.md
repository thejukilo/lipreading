# Desktop app — set up and run without the terminal

A single window replaces the terminal and the old preview window: pick your
devices, hit **Start**, and use push-to-talk. Your choices are saved to
`~/.lipreading/config.json` and remembered next time.

## First run

One-time (in a terminal, once):
```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```
Install **VB-Cable** if you haven't: https://vb-audio.com/Cable/ → run as admin →
reboot. Then from then on just **double-click `run.bat`** — no terminal.

> If the app doesn't appear, run **`run_debug.bat`** instead: it keeps a console
> open and prints the error.
>
> The launchers auto-find your virtual env in the repo root **or one level up**
> (`.venv`/`venv`). If yours is elsewhere, open `run.bat` and set the `VENV=`
> line to its folder.

## The window

**Setup panel (left):**
- **Camera** — your webcam (auto-detected; "Refresh devices" to rescan).
- **Microphone to Meet** — the output the voice is sent to. Auto-selects
  **CABLE Input** (VB-Cable). If it's missing you'll see a red hint to install
  VB-Cable. In Meet, set the mic to **CABLE Output**.
- **Hear it on my speakers (monitor)** + **Monitor speakers** — play the voice
  locally too, so you hear what's sent. Turn off if a second device already
  plays the meeting audio back (avoids double audio).
- **Voice** — Piper (natural, local) or the Windows built-in voice.
- **Push-to-talk key** — the key you hold to speak (default Right Ctrl). It's
  global, so it works while you're focused on the Meet tab.
- **Speak immediately** — skip the review step and speak on release.

**Right side:** live preview, the transcript box, **Speak ▶ / Discard**, and the
big **Start / Stop** button plus an on-screen **Hold to Talk** button.

## Using it

1. Press **Start** (first start loads the model — a few seconds).
2. Frame your face in the preview.
3. **Hold your push-to-talk key** (or the Hold to Talk button) and mouth a
   sentence; release.
4. In review mode: the text appears in the box — fix it if needed, then
   **Speak ▶** (or Discard). In "speak immediately" mode it's sent straight away.
5. Meet hears it through the virtual mic. Others hear it; you hear it too if the
   monitor is on.

## Notes

- **Changing camera/voice/mic** takes effect on the next Start (press Stop then
  Start). Model loading happens only on the first Start.
- **Both this app and Meet want the webcam** — if you're also on-camera in Meet,
  use OBS Virtual Camera to share one feed (see `docs/step2-live-meet.md`).
- The terminal front-end (`python -m server.live_app`) still exists and shares
  the same engine; the GUI is just the friendly face on it.
