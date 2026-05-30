"""
Temp file lifecycle management.

Strategy:
  1. Each download writes to a unique UUID-named file in app/temp/.
  2. After the StreamingResponse finishes, a BackgroundTask calls delete_file().
  3. A periodic sweep (called at startup) removes any stale files older than
     MAX_FILE_AGE_MINUTES – catches files from crashed requests.
"""

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def generate_temp_path(extension: str) -> Path:
    """
    Create a unique file path inside the temp directory.
    Extension should NOT include the leading dot, e.g. 'mp4', 'mp3'.
    """
    filename = f"{uuid.uuid4().hex}.{extension}"
    return settings.TEMP_DIR / filename


def delete_file(path: Path) -> None:
    """Safely delete a single file. Logs but does not raise on failure."""
    try:
        if path.exists():
            path.unlink()
            logger.debug("Deleted temp file: %s", path.name)
    except Exception as exc:
        logger.warning("Could not delete temp file %s: %s", path, exc)


async def delete_file_async(path: Path) -> None:
    """Async wrapper so BackgroundTasks can await it."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, delete_file, path)


def sweep_old_temp_files() -> int:
    """
    Remove temp files older than MAX_FILE_AGE_MINUTES.
    Returns the count of deleted files.
    Designed to be called at app startup and optionally on a schedule.
    """
    cutoff = time.time() - (settings.MAX_FILE_AGE_MINUTES * 60)
    deleted = 0
    try:
        for f in settings.TEMP_DIR.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                delete_file(f)
                deleted += 1
    except Exception as exc:
        logger.error("Error sweeping temp directory: %s", exc)
    if deleted:
        logger.info("Startup sweep removed %d stale temp file(s)", deleted)
    return deleted
