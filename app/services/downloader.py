"""
Download service — pytubefix for stream selection, ffmpeg for merging/conversion.

HOW IT WORKS
─────────────
1. pytubefix fetches the direct CDN stream URLs from YouTube
   (bypasses datacenter-IP bot detection that blocks yt-dlp).
2. Streams are downloaded to app/temp/ as raw files.
3. For quality > 360p: video-only + audio-only streams are downloaded
   separately, then merged by ffmpeg into a single MP4.
4. For MP3: the best audio stream is downloaded and re-encoded by ffmpeg.
5. FastAPI's StreamingResponse reads the final file in 1 MB chunks and
   sends them to the client. A BackgroundTask deletes the temp file after
   streaming completes.
"""

import asyncio
import os
import pathlib
import subprocess
import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiofiles
from pytubefix import YouTube
from pytubefix.exceptions import VideoUnavailable, VideoPrivate, RegexMatchError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.requests import AudioQuality, VideoQuality
from app.utils.validators import sanitize_filename

logger = get_logger(__name__)


# ── OAuth helper ─────────────────────────────────────────────────────────────

def _has_oauth_token() -> bool:
    """Return True if a cached OAuth token exists on disk."""
    try:
        from pytubefix.innertube import _token_file
        return pathlib.Path(_token_file).exists()
    except Exception:
        return False


def _make_yt(url: str) -> YouTube:
    """
    Try multiple pytubefix client/auth combos until one returns a valid
    YouTube object with accessible streams.

    Fallback order (server-IP safe):
      1. default client + OAuth  — TV client with auth, works for many videos
      2. WEB client, no OAuth    — unauthenticated web, works on some server IPs
      3. MWEB client, no OAuth   — mobile web, different headers
    Raises VideoUnavailable if all attempts fail.
    """
    has_token = _has_oauth_token()

    attempts = []
    if has_token:
        attempts.append({"use_oauth": True,  "allow_oauth_cache": True,  "client": None})
    attempts.append(    {"use_oauth": False, "allow_oauth_cache": False, "client": "WEB"})
    attempts.append(    {"use_oauth": False, "allow_oauth_cache": False, "client": "MWEB"})

    last_exc: Exception = VideoUnavailable("all clients failed")
    for kwargs in attempts:
        client = kwargs.pop("client")
        try:
            if client:
                yt = YouTube(url, client=client, **kwargs)
            else:
                yt = YouTube(url, **kwargs)
            # Probe title to confirm the video is reachable
            _ = yt.title
            return yt
        except (VideoUnavailable, VideoPrivate):
            raise          # no point retrying — video itself is restricted
        except Exception as exc:
            last_exc = exc
            continue

    raise last_exc


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg synchronously. Raises RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["ffmpeg", "-y", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-500:]}")


def _resolution_to_height(quality: VideoQuality) -> Optional[int]:
    """Convert VideoQuality enum to pixel height for stream selection."""
    mapping = {
        VideoQuality.Q1080: 1080,
        VideoQuality.Q720: 720,
        VideoQuality.Q480: 480,
        VideoQuality.Q360: 360,
        VideoQuality.Q240: 240,
        VideoQuality.Q144: 144,
    }
    return mapping.get(quality)


def _pick_video_stream(yt: YouTube, quality: VideoQuality):
    """
    Pick the best video stream for the requested quality.
    Returns a pytubefix Stream object.

    Strategy:
      - "best": highest adaptive (video-only) stream available
      - Specific quality: exact match first, next-lowest fallback
    """
    target_height = _resolution_to_height(quality)

    # Try adaptive video-only streams first (higher quality)
    adaptive = yt.streams.filter(only_video=True, file_extension="mp4").order_by("resolution").desc()

    if quality == VideoQuality.BEST:
        return adaptive.first() or yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").first()

    # Find exact match or nearest lower resolution
    for s in adaptive:
        if s.height and s.height <= target_height:
            return s

    # Fall back to progressive stream
    progressive = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc()
    for s in progressive:
        if s.resolution and int(s.resolution.replace("p", "")) <= target_height:
            return s

    return adaptive.last() or progressive.last()


def _pick_audio_stream(yt: YouTube):
    """Pick the best available audio stream (prefer mp4/m4a for ffmpeg compat)."""
    stream = (
        yt.streams.filter(only_audio=True, mime_type="audio/mp4").order_by("abr").desc().first()
        or yt.streams.filter(only_audio=True).order_by("abr").desc().first()
    )
    return stream


# ── Video Download ────────────────────────────────────────────────────────────

async def download_video(url: str, quality: VideoQuality) -> tuple[Path, str]:
    """
    Download a YouTube video as MP4.
    High-quality streams (>360p) are merged from separate video+audio tracks.

    Returns: (temp_file_path, safe_filename_for_download_header)
    """
    uid = uuid.uuid4().hex
    final_path = settings.TEMP_DIR / f"{uid}.mp4"

    def _run() -> str:
        try:
            yt = _make_yt(url)
            title = yt.title
        except (VideoPrivate, VideoUnavailable, RegexMatchError) as exc:
            raise ValueError(str(exc))

        video_stream = _pick_video_stream(yt, quality)
        if not video_stream:
            raise RuntimeError("No suitable video stream found for the requested quality.")

        is_progressive = video_stream.is_progressive

        if is_progressive:
            # Single combined stream — download directly
            logger.info("Downloading progressive stream: %s", video_stream.resolution)
            video_stream.download(output_path=str(settings.TEMP_DIR), filename=f"{uid}.mp4")
        else:
            # Adaptive stream — download video + audio separately then merge
            logger.info("Downloading adaptive video stream: %s", video_stream.resolution)
            video_tmp = settings.TEMP_DIR / f"{uid}_v.mp4"
            audio_tmp = settings.TEMP_DIR / f"{uid}_a.mp4"

            video_stream.download(output_path=str(settings.TEMP_DIR), filename=f"{uid}_v.mp4")

            audio_stream = _pick_audio_stream(yt)
            if audio_stream:
                audio_stream.download(output_path=str(settings.TEMP_DIR), filename=f"{uid}_a.mp4")
                # Merge video + audio with ffmpeg (copy streams, no re-encode)
                _run_ffmpeg(["-i", str(video_tmp), "-i", str(audio_tmp), "-c", "copy", str(final_path)])
                video_tmp.unlink(missing_ok=True)
                audio_tmp.unlink(missing_ok=True)
            else:
                # No audio stream — just rename the video file
                video_tmp.rename(final_path)

        return title

    loop = asyncio.get_event_loop()
    try:
        title = await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        final_path.unlink(missing_ok=True)
        raise TimeoutError("Download timed out. Try a lower quality or a shorter video.")
    except ValueError as exc:
        raise PermissionError(str(exc))

    if not final_path.exists() or final_path.stat().st_size == 0:
        raise RuntimeError("Download completed but output file is missing or empty.")

    safe_name = f"{sanitize_filename(title)}.mp4"
    logger.info("Video downloaded: %s -> %s (%d bytes)", title, final_path.name, final_path.stat().st_size)
    return final_path, safe_name


# ── Audio Download ────────────────────────────────────────────────────────────

async def download_audio(url: str, quality: AudioQuality) -> tuple[Path, str]:
    """
    Download the audio track of a YouTube video and convert to MP3.

    Returns: (temp_file_path, safe_filename_for_download_header)
    """
    uid = uuid.uuid4().hex
    raw_path = settings.TEMP_DIR / f"{uid}_raw"   # will get ext from pytubefix
    mp3_path = settings.TEMP_DIR / f"{uid}.mp3"

    def _run() -> str:
        try:
            yt = _make_yt(url)
            title = yt.title
        except (VideoPrivate, VideoUnavailable, RegexMatchError) as exc:
            raise ValueError(str(exc))

        audio_stream = _pick_audio_stream(yt)
        if not audio_stream:
            raise RuntimeError("No audio stream found for this video.")

        ext = audio_stream.subtype or "mp4"
        raw_file = settings.TEMP_DIR / f"{uid}_raw.{ext}"

        logger.info("Downloading audio stream: %s kbps %s", audio_stream.abr, ext)
        audio_stream.download(output_path=str(settings.TEMP_DIR), filename=f"{uid}_raw.{ext}")

        # Convert to MP3 at requested bitrate
        _run_ffmpeg([
            "-i", str(raw_file),
            "-vn",                         # drop video
            "-ar", "44100",                # sample rate
            "-ac", "2",                    # stereo
            "-b:a", f"{quality.value}k",   # bitrate
            str(mp3_path),
        ])
        raw_file.unlink(missing_ok=True)
        return title

    loop = asyncio.get_event_loop()
    try:
        title = await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        mp3_path.unlink(missing_ok=True)
        raise TimeoutError("Audio download timed out.")
    except ValueError as exc:
        raise PermissionError(str(exc))

    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        raise RuntimeError("Audio conversion completed but MP3 file is missing or empty.")

    safe_name = f"{sanitize_filename(title)}.mp3"
    logger.info("Audio downloaded: %s -> %s (%d bytes)", title, mp3_path.name, mp3_path.stat().st_size)
    return mp3_path, safe_name


# ── Streaming helper ──────────────────────────────────────────────────────────

async def file_stream_generator(path: Path) -> AsyncGenerator[bytes, None]:
    """
    Async generator that reads a file in CHUNK_SIZE chunks.
    Used with FastAPI's StreamingResponse — client receives data immediately
    without waiting for the full file to be in memory.
    """
    async with aiofiles.open(path, "rb") as f:
        while True:
            chunk = await f.read(settings.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
