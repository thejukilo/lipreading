"""Multi-user lipreading backend (FastAPI).

Phase A wires up the database, authentication and health. Later phases add the
per-user speak loop (/api/utter), voices, and background personalization,
registered here as additional routers.

Run locally:

    uvicorn server.api.main:app --reload --port 8000

or ``python -m server.api``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .db import init_db
from .routers import auth, teach, utter, voices

_WEB = os.path.join(os.path.dirname(__file__), "web")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    worker = None
    # Background training worker. Disabled in tests (they drive process_job
    # directly with a fake trainer); otherwise runs the real finetune().
    if not os.environ.get("LIPREADING_DISABLE_WORKER"):
        from .training import TrainingWorker

        worker = TrainingWorker()
        worker.start()
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Lipreading API", version="0.1.0", lifespan=_lifespan)

    # The web PWA is served from a different origin during dev (Vite on :5173),
    # so allow cross-origin calls. We use bearer tokens (not cookies), so no
    # credentialed CORS is needed. Tighten origins in production via env.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(utter.router)
    app.include_router(voices.router)
    app.include_router(teach.router)

    # ---- static PWA (same origin as the API, so bearer tokens Just Work) ----
    def _web(name: str, media: str | None = None):
        return FileResponse(os.path.join(_WEB, name), media_type=media)

    @app.get("/", include_in_schema=False)
    def index():
        return _web("index.html", "text/html")

    @app.get("/app.js", include_in_schema=False)
    def app_js():
        return _web("app.js", "application/javascript")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return _web("manifest.webmanifest", "application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        # Served from root so its scope covers the whole app.
        return _web("sw.js", "application/javascript")

    @app.get("/icon.svg", include_in_schema=False)
    def icon():
        return _web("icon.svg", "image/svg+xml")

    return app


app = create_app()
