"""
Pydantic response models (output shape + documentation).

Defining explicit response models:
  - auto-generates accurate OpenAPI /docs schemas
  - prevents leaking internal fields by accident
  - makes the API contract clear to frontend developers
"""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class FormatInfo(BaseModel):
    """Describes a single available stream format."""
    format_id: str
    ext: str
    resolution: Optional[str] = None   # e.g. "1280x720"
    quality_label: Optional[str] = None # e.g. "720p"
    filesize: Optional[int] = None       # bytes, None if unknown
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    fps: Optional[float] = None
    tbr: Optional[float] = None          # total bitrate kbps


class SubtitleInfo(BaseModel):
    language: str
    url: str
    ext: str


class VideoInfoResponse(BaseModel):
    """Response body for POST /api/info"""
    video_id: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None        # seconds
    uploader: Optional[str] = None
    uploader_url: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    description: Optional[str] = None
    upload_date: Optional[str] = None     # YYYYMMDD string from yt-dlp
    webpage_url: str
    is_live: bool = False
    formats: List[FormatInfo] = []
    subtitles: Dict[str, List[SubtitleInfo]] = {}

    model_config = {"from_attributes": True}


class PlaylistVideoItem(BaseModel):
    """One entry inside a playlist response."""
    index: int
    video_id: str
    title: str
    url: str
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None


class PlaylistInfoResponse(BaseModel):
    """Response body for POST /api/playlist"""
    playlist_id: str
    title: str
    uploader: Optional[str] = None
    video_count: int
    videos: List[PlaylistVideoItem] = []


class ErrorResponse(BaseModel):
    """Standard error envelope – used for all non-2xx responses."""
    error: str
    detail: Optional[str] = None
    status_code: int
