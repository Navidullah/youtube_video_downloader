"""
URL and input validation utilities.

Centralising validation here means the same rules apply to every
endpoint without copy-pasting regex patterns.
"""

import re
from typing import Optional


# Regex covers every known YouTube URL format:
#   https://www.youtube.com/watch?v=...
#   https://youtu.be/...
#   https://youtube.com/shorts/...
#   https://www.youtube.com/playlist?list=...
#   https://www.youtube.com/embed/...
#   http variants
#   Mobile m.youtube.com variants
_YOUTUBE_PATTERN = re.compile(
    r"^(https?://)?"                         # optional scheme
    r"(www\.|m\.)?"                          # optional www / mobile
    r"(youtube\.com|youtu\.be)"              # domain
    r"(/watch\?.*v=[\w-]+"                   # standard watch
    r"|/shorts/[\w-]+"                       # Shorts
    r"|/embed/[\w-]+"                        # embed
    r"|/v/[\w-]+"                            # old /v/ format
    r"|/playlist\?.*list=[\w-]+"             # playlist
    r"|/[\w-]+)"                             # channel / handle
    r".*$",
    re.IGNORECASE,
)


def is_valid_youtube_url(url: str) -> bool:
    """Return True if the string looks like a reachable YouTube URL."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    # Basic length guard – real URLs are at most ~2083 chars
    if len(url) > 2083:
        return False
    return bool(_YOUTUBE_PATTERN.match(url))


def extract_video_id(url: str) -> Optional[str]:
    """
    Best-effort extraction of the 11-char YouTube video ID.
    Returns None for playlist-only URLs.
    """
    patterns = [
        r"(?:v=|/shorts/|/embed/|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def is_playlist_url(url: str) -> bool:
    """Return True if the URL points to a playlist (list= param present)."""
    return "list=" in url and "playlist" in url.lower()


def sanitize_filename(name: str, max_length: int = 100) -> str:
    """
    Strip characters that are illegal in file names or HTTP headers.
    HTTP Content-Disposition filenames must be latin-1 safe (no emoji, no
    non-ASCII chars), so we encode to ASCII with 'ignore' to drop anything
    outside the ASCII range, then clean up filesystem-illegal characters.
    """
    # Drop non-ASCII characters (emoji, Arabic, CJK, etc.) — HTTP headers are latin-1
    ascii_name = name.encode("ascii", errors="ignore").decode("ascii")
    # Replace filesystem-illegal characters with underscore
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", ascii_name)
    # Collapse multiple underscores/spaces
    sanitized = re.sub(r"[ _]{2,}", "_", sanitized).strip("_. ")
    return sanitized[:max_length] if sanitized else "download"
