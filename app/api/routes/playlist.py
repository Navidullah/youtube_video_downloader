"""
POST /api/playlist  –  extract playlist metadata (no downloads).

Returns the playlist title, uploader, and a list of video entries
with titles, durations, and thumbnails. Capped at MAX_PLAYLIST_ITEMS
to prevent abuse.
"""

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import get_logger
from app.models.requests import PlaylistRequest
from app.models.responses import ErrorResponse, PlaylistInfoResponse
from app.services.youtube import get_playlist_info
from app.utils.validators import is_playlist_url

logger = get_logger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "/playlist",
    response_model=PlaylistInfoResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Extract playlist metadata",
    description=(
        "Returns the title, uploader and per-video metadata for a YouTube playlist. "
        f"Limited to a maximum of {settings.MAX_PLAYLIST_ITEMS} items per request."
    ),
)
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def get_playlist(request: Request, body: PlaylistRequest) -> PlaylistInfoResponse:
    if not is_playlist_url(body.url):
        raise HTTPException(
            status_code=400,
            detail="URL does not appear to be a YouTube playlist. Make sure it contains 'list='.",
        )

    logger.info("Playlist request: %s [max_items=%s]", body.url, body.max_items)

    try:
        return await get_playlist_info(body.url, body.max_items)

    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc))
    except Exception as exc:
        logger.exception("Playlist extraction failed: %s", exc)
        raise HTTPException(status_code=500, detail="Playlist extraction failed. Please try again.")
