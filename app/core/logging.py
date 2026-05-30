"""
Structured logging configuration.
Uses Python's built-in logging with a clean format that works well
in both local terminals and Render's log viewer.
"""

import logging
import sys
from app.core.config import settings


def setup_logging() -> None:
    """Call once at application startup to configure root logger."""

    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler – writes to stdout so Render captures it
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Avoid duplicate handlers if setup_logging() is called more than once
    if not root.handlers:
        root.addHandler(handler)

    # Quieten noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Use in every module:  logger = get_logger(__name__)"""
    return logging.getLogger(name)
