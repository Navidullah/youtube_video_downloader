"""
Download endpoints:
  POST /api/download/video  –  stream an MP4 file to the client
  POST /api/download/audio  –  stream an MP3 file to the client

Both endpoints follow the same pattern:
  1. Validate the request (Pydantic does this automatically)
  2. Call the appropriate service function to download + convert the file
  3. Return a StreamingResponse that sends the file in chunks
  4. Register a BackgroundTask to delete the temp file after streaming

Why BackgroundTask?
  FastAPI's BackgroundTask runs AFTER the response is fully sent to the client.
  This means the temp file exists while streaming but is cleaned up immediately
  after, without any manual polling loop.

Why StreamingResponse?
  A 1080p video can be 500 MB+. Loading it into RAM before sending would
  crash a small Render instance. StreamingResponse reads and sends one chunk
  at a time, keeping memory usage flat regardless of file size.
"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import get_logger
from app.models.requests import AudioDownloadRequest, VideoDownloadRequest
from app.models.responses import ErrorResponse
from app.services.downloader import download_audio, download_video, file_stream_generator
from app.utils.cleanup import delete_file

logger = get_logger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ── Video ─────────────────────────────────────────────────────────────────────

@router.post(
    "/download/video",
    responses={
        200: {"content": {"video/mp4": {}}, "description": "MP4 video stream"},
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Download MP4 video",
    description=(
        "Downloads a YouTube video as MP4 at the specified quality. "
        "Supports normal videos, Shorts, and any resolution from 144p to 1080p (or best). "
        "High-quality streams are automatically merged via ffmpeg."
    ),
)
@limiter.limit(f"{settings.RATE_LIMIT_DOWNLOAD_PER_MINUTE}/minute")
async def download_video_endpoint(
    request: Request,
    body: VideoDownloadRequest,
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    logger.info("Video download request: %s [quality=%s]", body.url, body.quality.value)

    try:
        temp_path, filename = await download_video(body.url, body.quality)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc))
    except Exception as exc:
        logger.exception("Video download failed: %s", exc)
        raise HTTPException(status_code=500, detail="Download failed. Please try again.")

    # Schedule temp file deletion after streaming completes
    background_tasks.add_task(delete_file, temp_path)

    file_size = temp_path.stat().st_size

    return StreamingResponse(
        content=file_stream_generator(temp_path),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(file_size),
            "X-File-Name": filename,
        },
    )


# ── Audio ─────────────────────────────────────────────────────────────────────

@router.post(
    "/download/audio",
    responses={
        200: {"content": {"audio/mpeg": {}}, "description": "MP3 audio stream"},
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Download MP3 audio",
    description=(
        "Extracts and converts the audio track of a YouTube video to MP3. "
        "Supports 128 / 192 / 320 kbps quality settings."
    ),
)
@limiter.limit(f"{settings.RATE_LIMIT_DOWNLOAD_PER_MINUTE}/minute")
async def download_audio_endpoint(
    request: Request,
    body: AudioDownloadRequest,
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    logger.info("Audio download request: %s [quality=%s kbps]", body.url, body.quality.value)

    try:
        temp_path, filename = await download_audio(body.url, body.quality)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc))
    except Exception as exc:
        logger.exception("Audio download failed: %s", exc)
        raise HTTPException(status_code=500, detail="Audio conversion failed. Please try again.")

    background_tasks.add_task(delete_file, temp_path)

    file_size = temp_path.stat().st_size

    return StreamingResponse(
        content=file_stream_generator(temp_path),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(file_size),
            "X-File-Name": filename,
        },
    )
