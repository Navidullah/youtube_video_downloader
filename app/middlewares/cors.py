"""
CORS (Cross-Origin Resource Sharing) configuration.

Why CORS matters:
  Browsers block JavaScript from calling APIs on a different domain by default.
  Adding CORS headers tells the browser: "This API trusts requests from these origins."

For development:  allow "*" (all origins) so you can test from localhost:3000
For production:   set ALLOWED_ORIGINS=https://yourdomain.com in your .env or
                  Render environment variables.

The settings are imported from core/config.py, so changing them requires
only an environment variable update – no code change needed.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings


def add_cors_middleware(app: FastAPI) -> None:
    """Attach the CORSMiddleware to the FastAPI app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-File-Name", "Content-Length"],
    )
