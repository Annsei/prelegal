"""FastAPI entrypoint.

Mounts the API under `/api` and serves the static Next.js export from
`backend/static/` for everything else. The static directory is populated by
the Docker build and may be missing during local backend-only development;
in that case API routes still work but `/` returns 404.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import init_database
from app.routes import auth, chat, documents, health, templates

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_database()
    yield


def create_app(static_dir: Path = STATIC_DIR) -> FastAPI:
    instance = FastAPI(title="Prelegal", lifespan=lifespan)

    # Local dev runs the Next dev server on :3000 against this API on :8000,
    # which is cross-origin. Docker serves both from one origin, so CORS
    # stays off unless explicitly requested via env.
    cors_origins = [
        origin.strip()
        for origin in os.environ.get("PRELEGAL_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if cors_origins:
        instance.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    instance.include_router(health.router, prefix="/api")
    instance.include_router(auth.router, prefix="/api")
    instance.include_router(chat.router, prefix="/api")
    instance.include_router(documents.router, prefix="/api")
    instance.include_router(templates.router, prefix="/api")

    if not static_dir.is_dir():
        return instance

    static_root = static_dir.resolve()
    next_assets = static_root / "_next"
    if next_assets.is_dir():
        instance.mount(
            "/_next",
            StaticFiles(directory=next_assets),
            name="next-assets",
        )

    def safe_static_path(rel: str) -> Path | None:
        """Resolve `rel` under static_root, refusing path-traversal escapes."""
        candidate = (static_root / rel).resolve()
        try:
            candidate.relative_to(static_root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    @instance.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        # Try the literal asset (e.g. "favicon.ico" or "login.html"), then
        # the route's own .html file (Next static export emits one per page),
        # and fall back to index.html so client-side routing keeps working.
        for rel in (full_path, f"{full_path}.html"):
            resolved = safe_static_path(rel)
            if resolved is not None:
                return FileResponse(resolved)
        return FileResponse(static_root / "index.html")

    return instance


app = create_app()
