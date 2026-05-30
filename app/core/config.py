"""
Core configuration module.
Loads all settings from environment variables / .env file using pydantic-settings.
Central place to change any app-wide setting without touching business logic.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings
from pathlib import Path
from typing import List, Union


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "YouTube Downloader API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Server ───────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1  # keep 1 on Render free tier to avoid OOM

    # ── CORS ─────────────────────────────────────────────────────────────────
    # In .env use a plain string: ALLOWED_ORIGINS=*
    # or comma-separated:        ALLOWED_ORIGINS=https://myapp.com,http://localhost:3000
    ALLOWED_ORIGINS: str = "*"

    # ── Rate Limiting (slowapi) ───────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 10       # requests per IP per minute
    RATE_LIMIT_DOWNLOAD_PER_MINUTE: int = 3  # stricter limit for heavy endpoints

    # ── Download / Temp Storage ───────────────────────────────────────────────
    TEMP_DIR: Path = Path("app/temp")
    MAX_FILE_AGE_MINUTES: int = 30        # auto-delete temp files older than this
    DOWNLOAD_TIMEOUT: int = 300           # seconds before yt-dlp gives up (5 min)
    CHUNK_SIZE: int = 1024 * 1024         # 1 MB streaming chunks

    # ── yt-dlp ───────────────────────────────────────────────────────────────
    YT_DLP_COOKIES_FILE: str = ""         # optional path to Netscape cookies.txt
    MAX_PLAYLIST_ITEMS: int = 50          # cap playlist extraction to avoid abuse

    # ── Security ─────────────────────────────────────────────────────────────
    API_KEY: str = ""                     # optional bearer token guard (leave blank = disabled)

    @property
    def cors_origins(self) -> List[str]:
        """Parse ALLOWED_ORIGINS string → list for CORSMiddleware."""
        raw = self.ALLOWED_ORIGINS.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore",
    }


# Singleton – import this everywhere
settings = Settings()

# Make sure temp directory exists on startup
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
