# MVP web app — accounts, per-user voices & models

A multi-user product built around the existing ML (VSR engine, TTS cloning, LLM
cleanup, personalization). Backend is FastAPI + SQLite; the frontend is an
installable PWA (works on iPhone Safari and desktop). Everything runs on your PC
now and moves to the cloud by changing env vars.

    ┌──────────────┐   HTTPS    ┌────────────────────────────┐
    │ Web PWA      │ ─────────► │ FastAPI (server/api)        │
    │ (phone/web)  │  bearer    │  auth · voices · teach ·    │
    │ push-to-talk │  token     │  /utter · background trainer│
    └──────────────┘            └────────────┬───────────────┘
                                             │
                              SQLite + per-user media on disk
                              VSR engine · VoxCPM · finetune()

## Install

```bash
pip install -r requirements-app.txt          # backend (adds fastapi, sqlalchemy, jwt, bcrypt)
# plus your existing base install (torch, engine, tts, etc.) for real inference
```

## Run

```bash
uvicorn server.api.main:app --host 127.0.0.1 --port 8000
# or: python -m server.api --reload
```

Open http://localhost:8000 on your PC. To use it on your **iPhone**, put an
HTTPS tunnel in front (camera needs a secure context):

```bash
cloudflared tunnel --url http://localhost:8000     # no account needed
# or: ngrok http 8000
```

Open the tunnel's `https://…` URL on the phone → **Share → Add to Home Screen**
to install it as an app.

## What each screen does

- **Speak** — hold the button, mouth a sentence, release. Frames upload to
  `/api/utter`; you get the transcript back and hear it in your chosen voice.
  Uses your private model when you have one, else the base model.
- **Voices** — record ~8s (encoded to WAV in the browser) or upload a WAV, name
  it, save. Set a default, preview, delete. Cloning is zero-shot at speak time
  (VoxCPM).
- **Teach** — read the prompted sentences to the camera. Each clip is stored
  privately; once enough *new* ones accumulate
  (`LIPREADING_RETRAIN_THRESHOLD`, default 10) a background job fine-tunes a
  model **just for you** and activates it. "Train now" forces a run.

## Configuration (env vars)

| var | default | purpose |
|---|---|---|
| `LIPREADING_DATA_DIR` | `~/.lipreading/server` | DB + per-user media |
| `LIPREADING_DB_URL` | SQLite in DATA_DIR | point at Postgres for the cloud |
| `LIPREADING_JWT_SECRET` | persisted random | set a fixed secret in production |
| `LIPREADING_JWT_TTL` | 2592000 (30d) | session length (seconds) |
| `LIPREADING_RETRAIN_THRESHOLD` | 10 | new sentences that trigger auto-retrain |
| `LIPREADING_DISABLE_WORKER` | — | set to disable the background trainer |

## Security notes (MVP → cloud)

- Passwords are bcrypt-hashed (SHA-256 pre-hash); sessions are signed JWTs.
- Every media/route is scoped to the owning user id; one user's data is never
  reachable from another's token.
- For the cloud phase: set a fixed `LIPREADING_JWT_SECRET`, move to Postgres,
  put media in object storage (the storage layer is isolated for this), serve
  behind TLS, and restrict CORS origins.

## Data model

`User`, `Voice`, `TrainingSample`, `TrainingJob`, `PersonalModel` — media lives
on disk (paths in the DB), so the schema is unchanged when media moves to S3.
