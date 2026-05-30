"""
FastAPI application factory.

WHY FASTAPI IS FAST
────────────────────
FastAPI is built on top of Starlette (async web framework) and uses Python's
asyncio event loop. Unlike traditional WSGI frameworks (Flask, Django) that
create a new OS thread per request, FastAPI handles I/O-bound work (network
calls, file reads) asynchronously on a single thread. This means thousands of
concurrent requests can be served without spawning thousands of threads.

KEY CONCEPTS IN THIS FILE
──────────────────────────
• lifespan  – replaces @app.on_event("startup") / "shutdown" (modern FastAPI)
• APIRouter – groups related routes into modules (info, download, playlist)
• SlowAPI   – rate limiting middleware that counts requests per IP per minute
• BackgroundTasks – FastAPI's built-in mechanism to run code after a response
  is sent (used here for temp file cleanup)
"""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.routes import download, info, playlist
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.middlewares.cors import add_cors_middleware
from app.utils.cleanup import sweep_old_temp_files

# Logging must be configured before any other imports that log
setup_logging()
logger = get_logger(__name__)


# ── Rate Limiter (shared instance) ────────────────────────────────────────────
# All routers import this same limiter so they share the same per-IP counters.
limiter = Limiter(key_func=get_remote_address)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code inside the 'async with' runs at startup;
    code after 'yield' runs at shutdown.
    """
    logger.info("=" * 60)
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Debug mode: %s", settings.DEBUG)
    logger.info("Temp directory: %s", settings.TEMP_DIR.resolve())

    # Verify yt-dlp is importable
    try:
        import yt_dlp
        logger.info("yt-dlp version: %s", yt_dlp.version.__version__)
    except ImportError:
        logger.critical("yt-dlp is NOT installed! Run: pip install yt-dlp")
        sys.exit(1)

    # Verify ffmpeg is on PATH
    import shutil
    if shutil.which("ffmpeg") is None:
        logger.warning(
            "ffmpeg not found on PATH. High-quality video merging and MP3 "
            "conversion will FAIL. Install ffmpeg and add it to PATH."
        )
    else:
        logger.info("ffmpeg found at: %s", shutil.which("ffmpeg"))

    # Clean up any temp files left from a previous crashed run
    sweep_old_temp_files()

    logger.info("=" * 60)
    yield  # ← Application is running here

    # Shutdown cleanup
    logger.info("Shutting down %s", settings.APP_NAME)
    sweep_old_temp_files()


# ── Application Factory ───────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Production-ready YouTube downloader API. "
            "Supports videos, Shorts, playlists, MP4 and MP3 downloads."
        ),
        docs_url="/docs",       # Swagger UI
        redoc_url="/redoc",     # ReDoc
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    add_cors_middleware(app)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    # All routes share the /api prefix to keep the URL namespace clean and
    # make it easy to version later (e.g. /api/v2/...).
    app.include_router(info.router,     prefix="/api", tags=["Info"])
    app.include_router(download.router, prefix="/api", tags=["Download"])
    app.include_router(playlist.router, prefix="/api", tags=["Playlist"])

    # ── Global Exception Handlers ─────────────────────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        """Return a clean 422 with a human-readable message instead of Pydantic's raw output."""
        errors = []
        for err in exc.errors():
            field = " → ".join(str(loc) for loc in err["loc"])
            errors.append(f"{field}: {err['msg']}")
        return JSONResponse(
            status_code=422,
            content={"error": "Validation failed", "detail": errors},
        )

    @app.exception_handler(Exception)
    async def global_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": "Please try again later."},
        )

    # ── Health / Root Endpoints ───────────────────────────────────────────────

    @app.get("/", tags=["Health"], summary="Root check")
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
        }

    @app.get("/health", tags=["Health"], summary="Health check for Render")
    async def health():
        """
        Render pings this endpoint to decide if the service is healthy.
        Return 200 = healthy, anything else = unhealthy (triggers restart).
        """
        return {"status": "ok"}

    return app


# Create the app instance (used by uvicorn)
app = create_app()
