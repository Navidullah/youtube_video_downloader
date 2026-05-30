"""
POST /api/info  –  extract YouTube video metadata without downloading.

This is always the first call a frontend makes:
  1. User pastes a URL
  2. Frontend calls /api/info to get title, thumbnail, available formats
  3. User picks a quality → frontend calls /api/download/video or /api/download/audio
"""

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import get_logger
from app.models.requests import VideoInfoRequest
from app.models.responses import ErrorResponse, VideoInfoResponse
from app.services.youtube import get_video_info

logger = get_logger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "/info",
    response_model=VideoInfoResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid or unsupported URL"},
        403: {"model": ErrorResponse, "description": "Private / age-restricted / geo-blocked"},
        408: {"model": ErrorResponse, "description": "Extraction timed out"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Unexpected server error"},
    },
    summary="Extract video metadata",
    description=(
        "Fetches title, thumbnail, duration, uploader, available formats and "
        "subtitle tracks for a YouTube video, Short, or playlist URL. "
        "Does **not** download any media."
    ),
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def get_info(request: Request, body: VideoInfoRequest) -> VideoInfoResponse:
    logger.info("Info request for: %s", body.url)
    try:
        return await get_video_info(body.url)

    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error in /api/info: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again.")
