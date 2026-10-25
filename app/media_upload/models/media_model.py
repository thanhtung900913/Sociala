from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.media_upload.models.common import ResponseBody, Timestamp

MediaStatus = Literal["UPLOADING", "PROCESSING", "READY", "FAILED", "DELETED"]


class MediaResponseBody(ResponseBody):
    id: UUID
    content_type: str
    byte_size: int
    width: int | None
    height: int | None
    status: MediaStatus
    created_at: Timestamp
    download_url: str | None = None
    url_expires_at: Timestamp | None = None


class MediaUploadRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    byte_size: int = Field(gt=0, le=5 * 1024 * 1024, strict=True)
    width: int | None = Field(default=None, gt=0, strict=True)
    height: int | None = Field(default=None, gt=0, strict=True)


class MediaUploadInfo(BaseModel):
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


class MediaUploadResponseBody(ResponseBody):
    media_id: UUID
    status: MediaStatus
    upload: MediaUploadInfo


class MediaCompleteResponseBody(ResponseBody):
    media_id: UUID
    status: Literal["PROCESSING", "READY"]
