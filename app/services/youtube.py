"""
YouTube metadata extraction service — powered by pytubefix.

Why pytubefix instead of yt-dlp for info extraction?
  yt-dlp uses YouTube's internal API which triggers bot detection on
  datacenter IPs (Render, Vercel, AWS) unless PO tokens or cookies are
  supplied. pytubefix uses a different authentication flow that bypasses
  this detection entirely — no cookies, no PO tokens, no sign-in required.

  yt-dlp is still used for the actual download step (downloader.py)
  because it handles format merging (video+audio) and MP3 conversion
  via ffmpeg automatically.
"""

import asyncio
from typing import Any, Dict, List, Optional

from pytubefix import Playlist, YouTube
from pytubefix.exceptions import VideoUnavailable, VideoPrivate, RegexMatchError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.responses import (
    FormatInfo,
    PlaylistInfoResponse,
    PlaylistVideoItem,
    VideoInfoResponse,
)

logger = get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _streams_to_formats(yt: YouTube) -> List[FormatInfo]:
    """Convert pytubefix stream objects to our FormatInfo response model."""
    seen_resolutions: set = set()
    result: List[FormatInfo] = []

    # Adaptive video-only streams (separate video+audio, highest quality)
    for s in yt.streams.filter(only_video=True, file_extension="mp4").order_by("resolution").desc():
        res = s.resolution  # e.g. "1080p"
        if not res or res in seen_resolutions:
            continue
        seen_resolutions.add(res)
        height = int(res.replace("p", "")) if res.endswith("p") else None
        result.append(
            FormatInfo(
                format_id=str(s.itag),
                ext="mp4",
                resolution=f"{s.width}x{s.height}" if s.width and s.height else None,
                quality_label=res,
                filesize=s.filesize,
                vcodec=s.video_codec,
                acodec=None,
                fps=s.fps,
            )
        )

    # Progressive streams (video+audio combined — usually 360p, always available)
    for s in yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc():
        res = s.resolution
        if not res or res in seen_resolutions:
            continue
        seen_resolutions.add(res)
        result.append(
            FormatInfo(
                format_id=str(s.itag),
                ext="mp4",
                resolution=f"{s.width}x{s.height}" if s.width and s.height else None,
                quality_label=res,
                filesize=s.filesize,
                vcodec=s.video_codec,
                acodec=s.audio_codec,
                fps=s.fps,
            )
        )

    return result


# ── Public API ────────────────────────────────────────────────────────────────

async def get_video_info(url: str) -> VideoInfoResponse:
    """
    Extract full metadata for a single video or Short.
    Runs pytubefix in a thread pool so it doesn't block the async event loop.
    """

    def _extract() -> VideoInfoResponse:
        import pathlib

        def _has_token() -> bool:
            try:
                from pytubefix.innertube import _token_file
                return pathlib.Path(_token_file).exists()
            except Exception:
                return False

        def _build_yt() -> YouTube:
            """Try multiple client/auth combos until one works."""
            has_token = _has_token()
            attempts = []
            if has_token:
                attempts.append({"use_oauth": True,  "allow_oauth_cache": True,  "client": None})
            attempts.append(    {"use_oauth": False, "allow_oauth_cache": False, "client": "WEB"})
            attempts.append(    {"use_oauth": False, "allow_oauth_cache": False, "client": "MWEB"})

            last_exc: Exception = Exception("all clients failed")
            for kwargs in attempts:
                client = kwargs.pop("client")
                try:
                    yt = YouTube(url, client=client, **kwargs) if client else YouTube(url, **kwargs)
                    _ = yt.title  # probe
                    return yt
                except (VideoPrivate, VideoUnavailable):
                    raise
                except Exception as exc:
                    last_exc = exc
                    continue
            raise last_exc

        try:
            yt = _build_yt()   # title already probed inside _build_yt
        except VideoPrivate:
            raise PermissionError("This video is private and cannot be accessed.")
        except VideoUnavailable:
            raise ValueError("This video is unavailable or has been removed.")
        except RegexMatchError:
            raise ValueError("Could not parse this YouTube URL.")
        except Exception as exc:
            msg = str(exc).lower()
            if "age" in msg and "restrict" in msg:
                raise PermissionError("This video is age-restricted.")
            if "private" in msg:
                raise PermissionError("This video is private.")
            raise RuntimeError(f"Failed to fetch video info: {exc}")

        formats = _streams_to_formats(yt)

        return VideoInfoResponse(
            video_id=yt.video_id,
            title=yt.title,
            thumbnail=yt.thumbnail_url,
            duration=yt.length,
            uploader=yt.author,
            uploader_url=yt.channel_url,
            view_count=yt.views,
            like_count=None,
            description=(yt.description or "")[:500],
            upload_date=None,
            webpage_url=yt.watch_url,
            is_live=False,
            formats=formats,
            subtitles={},
        )

    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _extract),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise TimeoutError("Metadata extraction timed out.")


async def get_playlist_info(url: str, max_items: Optional[int] = None) -> PlaylistInfoResponse:
    """Extract playlist title + per-video metadata (no downloads)."""
    limit = min(max_items or settings.MAX_PLAYLIST_ITEMS, settings.MAX_PLAYLIST_ITEMS)

    def _extract() -> PlaylistInfoResponse:
        try:
            pl = Playlist(url)
            title = pl.title
            videos = []
            for idx, video_url in enumerate(pl.video_urls[:limit], start=1):
                try:
                    yt = YouTube(video_url)
                    videos.append(
                        PlaylistVideoItem(
                            index=idx,
                            video_id=yt.video_id,
                            title=yt.title,
                            url=yt.watch_url,
                            duration=yt.length,
                            thumbnail=yt.thumbnail_url,
                            uploader=yt.author,
                        )
                    )
                except Exception:
                    continue  # Skip unavailable videos silently

            return PlaylistInfoResponse(
                playlist_id=pl.playlist_id,
                title=title or "Unknown Playlist",
                uploader=None,
                video_count=len(videos),
                videos=videos,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch playlist: {exc}")

    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _extract),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise TimeoutError("Playlist extraction timed out.")
