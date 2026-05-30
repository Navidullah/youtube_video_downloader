"""
Pydantic request models (input validation).

Pydantic automatically validates types, gives clear error messages,
and generates OpenAPI docs – zero extra code required.
"""

from pydantic import BaseModel, field_validator, HttpUrl
from typing import Optional
from enum import Enum


# ── Enumerations ─────────────────────────────────────────────────────────────

class VideoQuality(str, Enum):
    """Supported video resolutions. 'best' lets yt-dlp pick the highest available."""
    BEST    = "best"
    Q1080   = "1080p"
    Q720    = "720p"
    Q480    = "480p"
    Q360    = "360p"
    Q240    = "240p"
    Q144    = "144p"


class AudioQuality(str, Enum):
    """MP3 bitrate choices."""
    HIGH   = "320"   # kbps
    MEDIUM = "192"
    LOW    = "128"


# ── Request Models ────────────────────────────────────────────────────────────

class VideoInfoRequest(BaseModel):
    """Body for POST /api/info"""
    url: str

    @field_validator("url")
    @classmethod
    def must_be_youtube(cls, v: str) -> str:
        from app.utils.validators import is_valid_youtube_url
        if not is_valid_youtube_url(v):
            raise ValueError("URL must be a valid YouTube link")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        }
    }


class VideoDownloadRequest(BaseModel):
    """Body for POST /api/download/video"""
    url: str
    quality: VideoQuality = VideoQuality.BEST

    @field_validator("url")
    @classmethod
    def must_be_youtube(cls, v: str) -> str:
        from app.utils.validators import is_valid_youtube_url
        if not is_valid_youtube_url(v):
            raise ValueError("URL must be a valid YouTube link")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "quality": "720p",
            }
        }
    }


class AudioDownloadRequest(BaseModel):
    """Body for POST /api/download/audio"""
    url: str
    quality: AudioQuality = AudioQuality.HIGH

    @field_validator("url")
    @classmethod
    def must_be_youtube(cls, v: str) -> str:
        from app.utils.validators import is_valid_youtube_url
        if not is_valid_youtube_url(v):
            raise ValueError("URL must be a valid YouTube link")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "quality": "320",
            }
        }
    }


class PlaylistRequest(BaseModel):
    """Body for POST /api/playlist"""
    url: str
    max_items: Optional[int] = None  # override global cap if needed

    @field_validator("url")
    @classmethod
    def must_be_youtube(cls, v: str) -> str:
        from app.utils.validators import is_valid_youtube_url
        if not is_valid_youtube_url(v):
            raise ValueError("URL must be a valid YouTube link")
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://www.youtube.com/playlist?list=PLxxxxxx",
                "max_items": 20,
            }
        }
    }
