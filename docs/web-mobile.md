# Mobile web app — lipread from a phone

Use the lipreader from a **phone browser** with the phone's own camera. The
heavy model can't run on a phone, so your PC (Windows + CUDA) runs a small web
server and the phone is a thin client: open the page, **hold a button** and mouth
a sentence, release — the phone uploads the camera frames, the PC transcribes +
synthesizes, and the **phone plays the voice out loud**.

```
phone browser ──(hold to talk → JPEG frames)──►  POST /api/utter  ──►  PC (model)
phone speaker ◄──────────( transcript + WAV audio )──────────────────────┘
```

Frames are grabbed off a `<canvas>` and sent as JPEGs, so it works the same on
iOS Safari and Android Chrome — no video-codec differences to worry about.

## Setup (on the PC)

```powershell
pip install -r requirements-web.txt
python -m server.web_api --preload
```

`--preload` loads the model at startup (otherwise it loads on the first request).
It reuses your **saved desktop settings** (`~/.lipreading/config.json`) — the
recognition model, voice, and text-cleanup you picked in the desktop app all
apply here. The server prints an access URL and token:

```
  Local:  http://127.0.0.1:8000/?k=Xy7...   <- token in the ?k= part
  token:  Xy7...
```

Double-clicking **`run_web.bat`** does the same in a visible terminal.

## Make it reachable from the phone (HTTPS tunnel)

Browsers only allow camera access over **HTTPS** (or `localhost`). The easiest
way to give the server an HTTPS address a phone can reach is a tunnel — no router
config, no certificates:

```powershell
cloudflared tunnel --url http://localhost:8000
```

(Install `cloudflared` first; or use `ngrok http 8000`.) It prints a public
`https://<random>.trycloudflare.com` URL. On the phone, open that URL **with the
token appended**:

```
https://<random>.trycloudflare.com/?k=Xy7...
```

Allow camera access when prompted, then hold the green **Hold to talk** button,
mouth a sentence, and release.

> **Security:** the token is the only thing protecting the server — anyone with
> the full URL can use your GPU and voice. Treat it like a password, and stop the
> tunnel when you're done. Set a fixed token with `--token` or the
> `LIPREADING_WEB_TOKEN` environment variable if you don't want a new one each run.

## Options

| Flag | Default | Notes |
|------|---------|-------|
| `--host` | `127.0.0.1` | Keep this local and put the tunnel in front of it. |
| `--port` | `8000` | Match your tunnel's target port. |
| `--token` | random | Fixed access token (else one is generated each run). |
| `--preload` | off | Load the model at startup instead of on the first request. |

## API (for the Chrome extension / other clients)

- `GET /health` → `{ok, loaded, load_error}`
- `POST /api/utter` (auth: `X-Access-Token` header **or** `?token=`) —
  multipart form:
  - `frames`: one or more JPEG files (webcam frames, ~25 fps, ≥ 8 of them)
  - `fps` (default 25), `speak` (default true), `cleanup` (default true)
  - returns `{text, audio (base64 WAV or null), audio_mime, frames}`

## Limits / notes

- **One at a time:** the GPU model is serialized, so concurrent phone requests
  queue. Fine for a person or two; not a multi-tenant service.
- **Push-to-talk only** (no live streaming yet) — matches the desktop app.
- **Voice plays on the phone.** If you instead want it to talk into a Google Meet
  running on the PC, that's the desktop app's virtual-mic path (see
  `docs/step2-live-meet.md`); the two can also run side by side.
- The mobile page is `server/static/mobile.html` — a single self-contained file.
