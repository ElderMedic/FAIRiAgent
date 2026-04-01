"""FastAPI application factory for FAIRifier API."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers.v1 import router as v1_router
from .storage.sqlite_store import SQLiteProjectStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "projects.db"

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

API_VERSION = "1.4.0"


def _resolve_frontend_file(
    base_dir: Path, requested_path: str
) -> Path | None:
    """Return a safe file path inside the built frontend directory."""
    if not requested_path:
        return None

    resolved_base = base_dir.resolve()
    candidate = (resolved_base / requested_path).resolve()
    try:
        candidate.relative_to(resolved_base)
    except ValueError:
        return None

    if not candidate.is_file():
        return None
    return candidate


def create_app(serve_frontend: bool | None = None) -> FastAPI:
    """Application factory.

    Parameters
    ----------
    serve_frontend:
        ``True``  – mount the built React SPA from ``frontend/dist``.
        ``False`` – API-only (for dev where Vite runs separately).
        ``None``  – auto-detect: serve if ``frontend/dist/index.html`` exists.
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    store = SQLiteProjectStore(str(DB_PATH))

    if serve_frontend is None:
        serve_frontend = (FRONTEND_DIST / "index.html").is_file()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = store
        logger.info("FAIRifier API started (store: SQLite @ %s)", DB_PATH)
        if serve_frontend:
            logger.info("Serving frontend from %s", FRONTEND_DIST)
        yield
        store.close()
        logger.info("FAIRifier API stopped")

    application = FastAPI(
        title="FAIRifier API",
        description="Automated FAIR metadata generation system",
        version=API_VERSION,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(v1_router)

    if serve_frontend and FRONTEND_DIST.is_dir():
        application.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_DIST / "assets")),
            name="static-assets",
        )

        @application.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            """Serve index.html for any non-API route (SPA client-side routing)."""
            file_path = _resolve_frontend_file(
                FRONTEND_DIST, full_path
            )
            if file_path is not None:
                return FileResponse(str(file_path))
            return FileResponse(str(FRONTEND_DIST / "index.html"))
    else:
        @application.get("/")
        async def root():
            return {
                "message": "FAIRifier API",
                "version": API_VERSION,
                "docs": "/docs",
            }

    return application


app = create_app()
