"""
YouTube metadata extraction service — yt-dlp + bgutil PO token.

yt-dlp with the WEB client + bgutil PO token server works for ALL public
YouTube videos from any server IP without cookies or manual authentication.
"""

import asyncio
from typing import Any, Dict, List, Optional

import yt_dlp

from app.core.config import settings
from app.core.logging import get_logger
from app.models.responses import (
    FormatInfo,
    PlaylistInfoResponse,
    PlaylistVideoItem,
    VideoInfoResponse,
)

logger = get_logger(__name__)

_BGUTIL_URL = "http://127.0.0.1:4416"


# ── yt-dlp base options ───────────────────────────────────────────────────────

def _info_ydl_opts() -> Dict[str, Any]:
    import shutil
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "ignore_no_formats_error": True,
        "extractor_args": {
            "youtube": {
                # android_vr: returns full 144p-4K DASH formats without PO tokens
                # web: fallback with bgutil PO tokens if android_vr is blocked
                "player_client": ["android_vr", "web"],
            },
            "youtubepot-bgutilhttp": {
                "base_url": [_BGUTIL_URL],
            },
        },
    }
    # Tell yt-dlp to use Node.js for cipher/n-challenge solving (EJS framework)
    node_path = shutil.which("node")
    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}
    return opts


# ── Format parsing ────────────────────────────────────────────────────────────

def _parse_formats(raw_formats: list) -> List[FormatInfo]:
    result = []
    seen: set = set()
    for f in (raw_formats or []):
        ext = f.get("ext", "")
        if ext in ("mhtml", "webp") or "storyboard" in f.get("format_id", "").lower():
            continue
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        if vcodec == "none" and acodec == "none":
            continue
        height = f.get("height")
        quality_label = f"{height}p" if height else None
        if quality_label and quality_label in seen:
            continue
        if quality_label:
            seen.add(quality_label)
        result.append(FormatInfo(
            format_id=f.get("format_id", ""),
            ext=ext,
            resolution=f.get("resolution"),
            quality_label=quality_label,
            filesize=f.get("filesize") or f.get("filesize_approx"),
            vcodec=vcodec if vcodec != "none" else None,
            acodec=acodec if acodec != "none" else None,
            fps=f.get("fps"),
            tbr=f.get("tbr"),
        ))
    return result


# ── Public API ────────────────────────────────────────────────────────────────

async def get_video_info(url: str) -> VideoInfoResponse:
    """Extract metadata for a single video or Short."""

    def _extract() -> Dict[str, Any]:
        with yt_dlp.YoutubeDL(_info_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError("No data returned for this URL.")
            if info.get("_type") == "playlist":
                entries = info.get("entries") or []
                if not entries:
                    raise ValueError("No videos found at this URL.")
                info = entries[0]
            return info

    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(None, _extract),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise TimeoutError("Metadata extraction timed out.")
    except yt_dlp.utils.DownloadError as exc:
        _raise_friendly(str(exc))

    formats = _parse_formats(info.get("formats") or [])

    return VideoInfoResponse(
        video_id=info.get("id", ""),
        title=info.get("title", "Unknown"),
        thumbnail=info.get("thumbnail"),
        duration=info.get("duration"),
        uploader=info.get("uploader"),
        uploader_url=info.get("uploader_url"),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        description=(info.get("description") or "")[:500],
        upload_date=info.get("upload_date"),
        webpage_url=info.get("webpage_url", url),
        is_live=bool(info.get("is_live")),
        formats=formats,
        subtitles={},
    )


async def get_playlist_info(url: str, max_items: Optional[int] = None) -> PlaylistInfoResponse:
    """Extract playlist metadata."""
    limit = min(max_items or settings.MAX_PLAYLIST_ITEMS, settings.MAX_PLAYLIST_ITEMS)

    def _extract() -> Dict[str, Any]:
        opts = _info_ydl_opts()
        opts["extract_flat"] = "in_playlist"
        opts["playlistend"] = limit
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError("No data returned for this URL.")
            return info

    loop = asyncio.get_event_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(None, _extract),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise TimeoutError("Playlist extraction timed out.")
    except yt_dlp.utils.DownloadError as exc:
        _raise_friendly(str(exc))

    entries = info.get("entries") or []
    videos = []
    for idx, entry in enumerate(entries, start=1):
        if not entry:
            continue
        vid_id = entry.get("id", "")
        videos.append(PlaylistVideoItem(
            index=idx,
            video_id=vid_id,
            title=entry.get("title", "Unknown"),
            url=entry.get("url") or f"https://www.youtube.com/watch?v={vid_id}",
            duration=entry.get("duration"),
            thumbnail=entry.get("thumbnail"),
            uploader=entry.get("uploader"),
        ))

    return PlaylistInfoResponse(
        playlist_id=info.get("id", ""),
        title=info.get("title", "Unknown Playlist"),
        uploader=info.get("uploader"),
        video_count=len(videos),
        videos=videos,
    )


# ── Error translation ─────────────────────────────────────────────────────────

def _raise_friendly(message: str) -> None:
    """Translate yt-dlp error strings into clean API errors. Always raises."""
    msg = message.lower()
    if "private video" in msg:
        raise PermissionError("This video is private.")
    if "age" in msg and ("restrict" in msg or "confirm" in msg):
        raise PermissionError("This video is age-restricted.")
    if "geo" in msg or "not available in your country" in msg:
        raise PermissionError("This video is geo-restricted in our server region.")
    if "unavailable" in msg or "removed" in msg:
        raise ValueError("This video is unavailable or has been removed.")
    if "sign in" in msg or "bot" in msg:
        raise PermissionError("YouTube is blocking this request. Please try again shortly.")
    raise RuntimeError(f"yt-dlp error: {message}")
