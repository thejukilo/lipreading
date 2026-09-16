# Cloud deployment — Supabase + RunPod GPU + native iOS

Target: **native iOS app** → **Supabase** (auth + Postgres + storage) →
**RunPod GPU pod** running this FastAPI backend.

```
 iOS (SwiftUI) ──Supabase Auth (email / Sign in with Apple)──► Supabase JWT
       │                                                          │
       └── HTTPS + JWT ─────────► RunPod GPU pod (FastAPI) ◄───────┘
                                    ├─ verifies Supabase JWT
                                    ├─ DB:    Supabase Postgres
                                    ├─ media: volume now / Supabase Storage later
                                    └─ GPU:   VSR + VoxCPM + personalization
```

The backend is already cloud-ready: set a few env vars and it verifies Supabase
tokens and talks to Postgres. It falls back to the built-in email/password auth
when `SUPABASE_JWT_SECRET` is unset (local dev/tests).

---

## 1. Supabase (you do this)

1. **Postgres URL** — Project Settings → Database → Connection string (URI). Use
   the connection **pooler** URI and convert the scheme to psycopg:
   `postgresql+psycopg://postgres.<ref>:<password>@<host>:6543/postgres`
   → this is `LIPREADING_DB_URL`.
2. **JWT secret** — Project Settings → API → JWT Settings → **JWT Secret**
   → this is `SUPABASE_JWT_SECRET`. (If your project shows only asymmetric keys,
   tell me — we'll switch verification to JWKS.)
3. **Enable Sign in with Apple** — Authentication → Providers → Apple. You'll
   paste in the Apple keys from step 3 below. Email/password can stay on too.
4. **Storage bucket** (for the later media move) — Storage → create a private
   bucket `media`. Not needed for first boot (media lives on the pod volume).

## 2. RunPod (you do this, I'll guide live)

1. Create a **GPU Pod** — a 16–24 GB card is plenty (RTX 4000 Ada / L4 / A4000).
2. Attach a **Network Volume** (say 30 GB) mounted at `/workspace`, and put:
   - `/workspace/third_party/auto_avsr` — the auto_avsr checkout
   - `/workspace/checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth` (+ any others)
3. Deploy the image built from this repo's `Dockerfile` (via RunPod's GitHub/
   container deploy), expose **HTTP port 8000** (RunPod gives you an HTTPS proxy
   URL automatically).
4. Set these **environment variables** on the pod:

   | var | value |
   |---|---|
   | `SUPABASE_JWT_SECRET` | from Supabase step 2 |
   | `LIPREADING_DB_URL` | from Supabase step 1 |
   | `LIPREADING_BASE_CHECKPOINT` | `/workspace/checkpoints/vsr_trlrs2lrs3vox2avsp_base.pth` |
   | `LIPREADING_AUTO_AVSR_DIR` | `/workspace/third_party/auto_avsr` |
   | `LIPREADING_DATA_DIR` | `/workspace/data` |

5. Hit `https://<pod>-8000.proxy.runpod.net/health` → `{"ok":true}`.

## 3. Apple (you do this)

1. In the Apple Developer portal: register an **App ID** with **Sign in with
   Apple** capability.
2. Create a **Services ID** + a **Sign in with Apple key** (.p8) — these values
   go into Supabase → Auth → Apple provider.
3. Keep your **Team ID** and **bundle identifier** handy for the Xcode project.

Apple's exact fields for Supabase are documented at
supabase.com/docs/guides/auth/social-login/auth-apple — I'll walk you through
mapping them when we wire the app.

---

## What's already done in this repo
- `Dockerfile` + `requirements-cloud.txt` — headless GPU image (no desktop deps).
- Supabase JWT verification + user provisioning (`SUPABASE_JWT_SECRET`).
- Postgres support (`LIPREADING_DB_URL`, psycopg).
- Env-driven model/auto_avsr/data paths for the mounted volume.

## Still to build (I'll do)
- **Native iOS app** (SwiftUI): Supabase auth, camera capture, Speak/Voices/
  Teach against this API.
- **Supabase Storage backend** for media (so the pod stays stateless) — after
  first boot works on the volume.
- Optional: split to serverless later to cut idle cost.
