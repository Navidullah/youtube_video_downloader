"""
Download service – handles MP4 video and MP3 audio downloads via yt-dlp.

HOW DOWNLOADING WORKS
─────────────────────
1. We build a yt-dlp format selector string that targets the requested quality.
2. yt-dlp downloads the best matching video + audio streams (separate files
   for high quality) and merges them via ffmpeg into a single MP4/MP3.
3. The merged file is written to app/temp/ under a UUID name.
4. FastAPI's StreamingResponse reads it in CHUNK_SIZE chunks and sends them
   to the client, so we never load the whole file into RAM.
5. A BackgroundTask deletes the temp file once streaming is done.

HOW FFMPEG MERGING WORKS
────────────────────────
YouTube streams video-only (VP9/AVC) and audio-only (Opus/AAC) separately for
resolutions above 360p. yt-dlp calls ffmpeg automatically when the format
selector is "bestvideo+bestaudio" to mux them into a single container.
For MP3, ffmpeg re-encodes the audio stream to MP3 at the requested bitrate.
"""

import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Dict, Any

import aiofiles
import yt_dlp

from app.core.config import settings
from app.core.logging import get_logger
from app.models.requests import AudioQuality, VideoQuality
from app.utils.cleanup import generate_temp_path
from app.utils.validators import sanitize_filename
from app.services.youtube import _base_ydl_opts, _raise_friendly

logger = get_logger(__name__)


# ── Format selector builder ───────────────────────────────────────────────────

def _video_format_selector(quality: VideoQuality) -> str:
    """
    Build a yt-dlp format selector string for the requested video quality.

    Examples:
      best  → bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best
      720p  → bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]
    """
    if quality == VideoQuality.BEST:
        return (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo+bestaudio"
            "/best"
        )

    height = quality.value.replace("p", "")  # "720p" → "720"
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={height}]+bestaudio"
        f"/best[height<={height}]"
        f"/best"
    )


# ── Video Download ────────────────────────────────────────────────────────────

async def download_video(url: str, quality: VideoQuality) -> tuple[Path, str]:
    """
    Download a YouTube video as MP4.

    Returns:
        (temp_file_path, safe_filename)

    The caller is responsible for deleting the temp file after streaming.
    """
    output_path = generate_temp_path("mp4")

    def _run_download() -> str:
        """Runs in a thread pool executor. Returns the final video title."""
        opts = _base_ydl_opts()
        opts.update(
            {
                "format": _video_format_selector(quality),
                "outtmpl": str(output_path),
                "merge_output_format": "mp4",
                # ffmpeg post-processor: re-encode to ensure H.264 + AAC compatibility
                "postprocessors": [
                    {
                        "key": "FFmpegVideoConvertor",
                        "preferedformat": "mp4",
                    }
                ],
                "socket_timeout": 60,
                # Abort rather than wait forever on a stalled download
                "retries": 3,
                "fragment_retries": 3,
            }
        )
        if settings.YT_DLP_COOKIES_FILE:
            opts["cookiefile"] = settings.YT_DLP_COOKIES_FILE

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info.get("title", "video") if info else "video"

    loop = asyncio.get_event_loop()
    try:
        title = await asyncio.wait_for(
            loop.run_in_executor(None, _run_download),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        output_path.unlink(missing_ok=True)
        raise TimeoutError("Download timed out. Try a lower quality or shorter video.")
    except yt_dlp.utils.DownloadError as exc:
        output_path.unlink(missing_ok=True)
        _raise_friendly(str(exc))

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Download completed but output file is missing or empty.")

    safe_name = f"{sanitize_filename(title)}.mp4"
    logger.info("Video downloaded: %s → %s (%d bytes)", title, output_path.name, output_path.stat().st_size)
    return output_path, safe_name


# ── Audio Download ────────────────────────────────────────────────────────────

async def download_audio(url: str, quality: AudioQuality) -> tuple[Path, str]:
    """
    Download a YouTube video's audio track and convert to MP3.

    Returns:
        (temp_file_path, safe_filename)
    """
    import uuid as _uuid
    # Use a fixed stem so we know exactly what path yt-dlp writes to.
    stem = _uuid.uuid4().hex
    base_path = settings.TEMP_DIR / stem          # no extension
    mp3_path = settings.TEMP_DIR / f"{stem}.mp3"  # where ffmpeg writes the output

    def _run_download() -> str:
        opts = _base_ydl_opts()
        opts.update(
            {
                "format": "bestaudio/best",
                # yt-dlp downloads to <stem>.<original_ext>, then ffmpeg converts to <stem>.mp3
                "outtmpl": str(base_path),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": quality.value,  # "320", "192", "128"
                    }
                ],
                "socket_timeout": 60,
                "retries": 3,
            }
        )

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info.get("title", "audio") if info else "audio"

    loop = asyncio.get_event_loop()
    try:
        title = await asyncio.wait_for(
            loop.run_in_executor(None, _run_download),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        mp3_path.unlink(missing_ok=True)
        raise TimeoutError("Audio download timed out.")
    except yt_dlp.utils.DownloadError as exc:
        mp3_path.unlink(missing_ok=True)
        _raise_friendly(str(exc))

    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        raise RuntimeError("Audio conversion completed but MP3 file is missing or empty.")

    safe_name = f"{sanitize_filename(title)}.mp3"
    logger.info("Audio downloaded: %s → %s (%d bytes)", title, mp3_path.name, mp3_path.stat().st_size)
    return mp3_path, safe_name


# ── Streaming helper ──────────────────────────────────────────────────────────

async def file_stream_generator(path: Path) -> AsyncGenerator[bytes, None]:
    """
    Async generator that reads a file in chunks.
    Used with FastAPI's StreamingResponse to avoid loading the
    entire file into memory before sending it to the client.

    How FastAPI streaming works:
      StreamingResponse accepts an async generator. FastAPI iterates it and
      sends each chunk as it becomes available, which means the client starts
      receiving data immediately without waiting for the full file.
    """
    async with aiofiles.open(path, "rb") as f:
        while True:
            chunk = await f.read(settings.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
