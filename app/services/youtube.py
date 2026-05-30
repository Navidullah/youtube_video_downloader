"""
YouTube metadata extraction service.

Uses yt-dlp's Python API (not subprocess) for:
  - extracting video info (title, formats, subtitles, …)
  - extracting playlist metadata

How yt-dlp works internally:
  YoutubeDL.extract_info(url, download=False) fetches only the JSON metadata
  from YouTube's internal API without downloading any media file. This is fast
  (~1-2 seconds) and returns a giant dict we parse into our clean response models.
"""

import asyncio
from typing import Any, Dict, Optional

import yt_dlp

from app.core.config import settings
from app.core.logging import get_logger
from app.models.responses import (
    FormatInfo,
    PlaylistInfoResponse,
    PlaylistVideoItem,
    SubtitleInfo,
    VideoInfoResponse,
)

logger = get_logger(__name__)


# ── yt-dlp option presets ─────────────────────────────────────────────────────

def _base_ydl_opts() -> Dict[str, Any]:
    """Common yt-dlp options shared by all operations."""
    opts: Dict[str, Any] = {
        "quiet": True,           # suppress yt-dlp's own console output
        "no_warnings": True,
        "socket_timeout": 30,    # network timeout per request
    }
    if settings.YT_DLP_COOKIES_FILE:
        opts["cookiefile"] = settings.YT_DLP_COOKIES_FILE
    return opts


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_formats(raw_formats: list) -> list[FormatInfo]:
    """Convert yt-dlp's raw format list into our FormatInfo models."""
    result = []
    for f in raw_formats:
        ext = f.get("ext", "")
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")

        # Skip storyboard / thumbnail formats
        if ext in ("mhtml", "webp") or "storyboard" in f.get("format_id", "").lower():
            continue

        height = f.get("height")
        quality_label = f"{height}p" if height else None

        result.append(
            FormatInfo(
                format_id=f.get("format_id", ""),
                ext=ext,
                resolution=f.get("resolution"),
                quality_label=quality_label,
                filesize=f.get("filesize") or f.get("filesize_approx"),
                vcodec=vcodec if vcodec != "none" else None,
                acodec=acodec if acodec != "none" else None,
                fps=f.get("fps"),
                tbr=f.get("tbr"),
            )
        )
    return result


def _parse_subtitles(raw_subs: dict) -> Dict[str, list[SubtitleInfo]]:
    """Parse the subtitles dict returned by yt-dlp."""
    result = {}
    for lang, tracks in raw_subs.items():
        parsed = []
        for track in tracks:
            parsed.append(
                SubtitleInfo(
                    language=lang,
                    url=track.get("url", ""),
                    ext=track.get("ext", "vtt"),
                )
            )
        if parsed:
            result[lang] = parsed
    return result


# ── Public API ────────────────────────────────────────────────────────────────

async def get_video_info(url: str) -> VideoInfoResponse:
    """
    Extract full metadata for a single video or Short.
    Runs yt-dlp in a thread pool so it doesn't block the async event loop.
    """
    def _extract() -> Dict[str, Any]:
        opts = _base_ydl_opts()
        # Use a very permissive selector so yt-dlp populates all format entries
        # but does not raise if a specific quality is unavailable
        opts["format"] = "bestvideo+bestaudio/bestvideo/bestaudio/best"
        opts["ignore_no_formats_error"] = True
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError("yt-dlp returned no data for this URL")
            # If it's a playlist URL pointing to a single video, unwrap
            if info.get("_type") == "playlist":
                entries = info.get("entries", [])
                if not entries:
                    raise ValueError("No videos found at this URL")
                info = entries[0]
            return info

    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(None, _extract),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise TimeoutError("Metadata extraction timed out")
    except yt_dlp.utils.DownloadError as exc:
        _raise_friendly(str(exc))

    formats = _parse_formats(info.get("formats") or [])
    subtitles = _parse_subtitles(info.get("subtitles") or {})

    return VideoInfoResponse(
        video_id=info.get("id", ""),
        title=info.get("title", "Unknown"),
        thumbnail=info.get("thumbnail"),
        duration=info.get("duration"),
        uploader=info.get("uploader"),
        uploader_url=info.get("uploader_url"),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        description=info.get("description", "")[:500] if info.get("description") else None,
        upload_date=info.get("upload_date"),
        webpage_url=info.get("webpage_url", url),
        is_live=bool(info.get("is_live")),
        formats=formats,
        subtitles=subtitles,
    )


async def get_playlist_info(url: str, max_items: Optional[int] = None) -> PlaylistInfoResponse:
    """Extract playlist title + per-video metadata (no downloads)."""
    limit = min(max_items or settings.MAX_PLAYLIST_ITEMS, settings.MAX_PLAYLIST_ITEMS)

    def _extract() -> Dict[str, Any]:
        opts = _base_ydl_opts()
        opts["extract_flat"] = "in_playlist"   # fast: no per-video full extraction
        opts["playlistend"] = limit
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError("yt-dlp returned no data for this URL")
            return info

    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(None, _extract),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise TimeoutError("Playlist extraction timed out")
    except yt_dlp.utils.DownloadError as exc:
        _raise_friendly(str(exc))

    entries = info.get("entries") or []
    videos = []
    for idx, entry in enumerate(entries, start=1):
        if not entry:
            continue
        vid_id = entry.get("id", "")
        videos.append(
            PlaylistVideoItem(
                index=idx,
                video_id=vid_id,
                title=entry.get("title", "Unknown"),
                url=entry.get("url") or f"https://www.youtube.com/watch?v={vid_id}",
                duration=entry.get("duration"),
                thumbnail=entry.get("thumbnail"),
                uploader=entry.get("uploader"),
            )
        )

    return PlaylistInfoResponse(
        playlist_id=info.get("id", ""),
        title=info.get("title", "Unknown Playlist"),
        uploader=info.get("uploader"),
        video_count=len(videos),
        videos=videos,
    )


# ── Error translation ─────────────────────────────────────────────────────────

def _raise_friendly(message: str) -> None:
    """
    Translate yt-dlp's raw error strings into human-readable API errors.
    Always raises – never returns.
    """
    msg_lower = message.lower()
    if "private video" in msg_lower:
        raise PermissionError("This video is private and cannot be accessed.")
    if "age" in msg_lower and "restricted" in msg_lower:
        raise PermissionError("This video is age-restricted. Sign-in cookies required.")
    if "geo" in msg_lower or "not available in your country" in msg_lower:
        raise PermissionError("This video is geo-restricted and not available in this region.")
    if "unavailable" in msg_lower or "removed" in msg_lower:
        raise ValueError("This video has been removed or is no longer available.")
    if "sign in" in msg_lower or "confirm your age" in msg_lower:
        raise PermissionError("YouTube requires sign-in for this video.")
    raise RuntimeError(f"yt-dlp error: {message}")
