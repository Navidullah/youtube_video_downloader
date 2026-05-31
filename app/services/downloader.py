"""
Download service — yt-dlp + bgutil PO token server.

HOW IT WORKS
─────────────
1. At startup (main.py), the bgutil PO token server starts on port 4416.
   bgutil generates YouTube Proof-of-Origin tokens by running YouTube's own
   JavaScript challenge, so yt-dlp's WEB client is treated as a real browser.

2. yt-dlp's yt-dlp-get-pot plugin reads the bgutil server URL from
   extractor_args and uses it to get a fresh PO token for each request.

3. yt-dlp downloads the best matching video/audio streams and merges them
   with ffmpeg into a single MP4 file in app/temp/.

4. FastAPI's StreamingResponse streams the file in 1 MB chunks to the client.
   A BackgroundTask deletes the temp file after streaming completes.
"""

import asyncio
from pathlib import Path
from typing import AsyncGenerator, Any, Dict

import aiofiles
import yt_dlp

from app.core.config import settings
from app.core.logging import get_logger
from app.models.requests import AudioQuality, VideoQuality
from app.services.youtube import _raise_friendly
from app.utils.cleanup import generate_temp_path
from app.utils.validators import sanitize_filename

logger = get_logger(__name__)

# Port where bgutil PO token server listens (started in main.py lifespan)
_BGUTIL_URL = "http://127.0.0.1:4416"


# ── yt-dlp options ────────────────────────────────────────────────────────────

def _base_ydl_opts() -> Dict[str, Any]:
    """Common yt-dlp options for all download operations."""
    import shutil
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_args": {
            "youtube": {
                "player_client": ["web"],
            },
            # bgutil HTTP server provides PO tokens
            "youtubepot-bgutilhttp": {
                "base_url": [_BGUTIL_URL],
            },
        },
    }
    # Configure Node.js for yt-dlp cipher/n-challenge solving (EJS framework)
    node_path = shutil.which("node")
    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}
    return opts


def _video_format_selector(quality: VideoQuality) -> str:
    """Build yt-dlp format selector string for the requested video quality."""
    if quality == VideoQuality.BEST:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    height = quality.value.replace("p", "")
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={height}]+bestaudio"
        f"/best[height<={height}]/best"
    )


# ── Video Download ────────────────────────────────────────────────────────────

async def download_video(url: str, quality: VideoQuality) -> tuple[Path, str]:
    """Download a YouTube video as MP4. Returns (temp_path, safe_filename)."""
    output_path = generate_temp_path("mp4")

    def _run() -> str:
        opts = _base_ydl_opts()
        opts.update({
            "format": _video_format_selector(quality),
            "outtmpl": str(output_path),
            "merge_output_format": "mp4",
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info.get("title", "video") if info else "video"

    loop = asyncio.get_event_loop()
    try:
        title = await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        output_path.unlink(missing_ok=True)
        raise TimeoutError("Download timed out. Try a lower quality or shorter video.")
    except yt_dlp.utils.DownloadError as exc:
        output_path.unlink(missing_ok=True)
        _raise_friendly(str(exc))
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed: {exc}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Download completed but output file is missing or empty.")

    safe_name = f"{sanitize_filename(title)}.mp4"
    logger.info("Video downloaded: %s (%d bytes)", output_path.name, output_path.stat().st_size)
    return output_path, safe_name


# ── Audio Download ────────────────────────────────────────────────────────────

async def download_audio(url: str, quality: AudioQuality) -> tuple[Path, str]:
    """Extract audio as MP3. Returns (temp_path, safe_filename)."""
    import uuid as _uuid
    stem = _uuid.uuid4().hex
    base_path = settings.TEMP_DIR / stem
    mp3_path = settings.TEMP_DIR / f"{stem}.mp3"

    def _run() -> str:
        opts = _base_ydl_opts()
        opts.update({
            "format": "bestaudio/best",
            "outtmpl": str(base_path),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality.value,
            }],
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info.get("title", "audio") if info else "audio"

    loop = asyncio.get_event_loop()
    try:
        title = await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        mp3_path.unlink(missing_ok=True)
        raise TimeoutError("Audio download timed out.")
    except yt_dlp.utils.DownloadError as exc:
        mp3_path.unlink(missing_ok=True)
        _raise_friendly(str(exc))
    except Exception as exc:
        mp3_path.unlink(missing_ok=True)
        raise RuntimeError(f"Audio download failed: {exc}")

    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        raise RuntimeError("Audio conversion completed but MP3 file is missing or empty.")

    safe_name = f"{sanitize_filename(title)}.mp3"
    logger.info("Audio downloaded: %s (%d bytes)", mp3_path.name, mp3_path.stat().st_size)
    return mp3_path, safe_name


# ── Streaming helper ──────────────────────────────────────────────────────────

async def file_stream_generator(path: Path) -> AsyncGenerator[bytes, None]:
    """Read a file in CHUNK_SIZE chunks for StreamingResponse."""
    async with aiofiles.open(path, "rb") as f:
        while True:
            chunk = await f.read(settings.CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
