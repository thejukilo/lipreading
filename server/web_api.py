"""Web API + mobile client so phones can lipread with their own camera.

The model is heavy (GPU), so it runs here on your PC; the phone is a thin
client: it opens its camera in the browser, records a short push-to-talk clip as
JPEG frames, uploads them, and plays back the synthesized voice the server
returns.

    phone browser ──(hold to talk: JPEG frames)──► POST /api/utter ──► PC
    phone speaker ◄────────(WAV audio + transcript)────────────────────┘

Because it's meant to be reached over the internet (through an HTTPS tunnel —
which also satisfies the browser's "camera needs a secure context" rule), every
request carries a shared access token. Run with ``python -m server.web_api``.
"""

# NB: no `from __future__ import annotations` here — FastAPI/pydantic must see the
# real UploadFile/Form types on the endpoint signatures, not stringized forward refs.

import argparse
import base64
import os
import secrets

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(service, token: str):
    """Build the FastAPI app around an InferenceService and an access token."""
    from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse, JSONResponse

    app = FastAPI(title="Lipreading mobile API", docs_url=None, redoc_url=None)

    def require_token(
        x_access_token: str | None = Header(default=None),
        token_q: str | None = Query(default=None, alias="token"),
    ) -> None:
        supplied = x_access_token or token_q or ""
        if not (token and secrets.compare_digest(supplied, token)):
            raise HTTPException(status_code=401, detail="bad or missing access token")

    @app.get("/")
    def index():
        # The page itself is not secret; API calls are what require the token.
        return FileResponse(os.path.join(_STATIC_DIR, "mobile.html"))

    @app.get("/health")
    def health():
        return {"ok": True, "loaded": service.loaded, "load_error": service.load_error}

    @app.post("/api/utter")
    def utter(
        _=Depends(require_token),
        frames: list[UploadFile] = File(...),
        fps: int = Form(25),
        speak: bool = Form(True),
        cleanup: bool = Form(True),
    ):
        from .inference_service import decode_jpeg_frames

        blobs = [f.file.read() for f in frames]
        arr = decode_jpeg_frames(blobs, max_side=480)
        if arr.shape[0] < 8:  # ~0.3s at 25fps — anything shorter isn't readable
            raise HTTPException(
                status_code=400,
                detail=f"only {int(arr.shape[0])} usable frame(s) — hold the button longer.",
            )
        try:
            text = service.transcribe(arr, cleanup=cleanup)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"transcription failed: {e}")
        if not text:
            return JSONResponse({"text": "", "audio": None, "frames": int(arr.shape[0]),
                                 "message": "empty transcript — try again"})
        audio_b64 = None
        if speak:
            try:
                wav = service.synthesize_wav(text)
                audio_b64 = base64.b64encode(wav).decode("ascii")
            except Exception as e:
                return JSONResponse({"text": text, "audio": None,
                                     "frames": int(arr.shape[0]),
                                     "message": f"voice failed: {e}"})
        return {"text": text, "audio": audio_b64, "audio_mime": "audio/wav",
                "frames": int(arr.shape[0])}

    return app


def _resolve_token(explicit: str | None) -> str:
    return (explicit or os.environ.get("LIPREADING_WEB_TOKEN")
            or secrets.token_urlsafe(9))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lipreading mobile web API.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address. Keep 127.0.0.1 and put a tunnel in front.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default=None,
                        help="Access token (default: $LIPREADING_WEB_TOKEN or random).")
    parser.add_argument("--preload", action="store_true",
                        help="Load the model at startup instead of on first request.")
    args = parser.parse_args(argv)

    import uvicorn

    from .inference_service import InferenceService

    token = _resolve_token(args.token)
    service = InferenceService()
    if args.preload:
        print("[web] preloading model…")
        try:
            service.load()
        except Exception as e:
            service.load_error = str(e)
            print(f"[web] preload failed (will retry on first request): {e}")

    app = create_app(service, token)

    print("\n" + "=" * 62)
    print("  Lipreading mobile server is starting.")
    print(f"  Local:  http://{args.host}:{args.port}/?k={token}")
    print("  To use from a phone, expose it over HTTPS with a tunnel, e.g.:")
    print(f"      cloudflared tunnel --url http://localhost:{args.port}")
    print("  then open the tunnel's https URL on the phone WITH  ?k=<token>")
    print(f"  token: {token}")
    print("=" * 62 + "\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
