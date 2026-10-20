from uuid import UUID

from pydantic import BaseModel

from app.backend.models.common import ResponseBody, Timestamp

class MediaUploadRequestBody(ResponseBody):
    content_type: str | None = None
    byte_size: int | None = None
    width: int | None = None
    height: int | None = None

class MediaUploadInfo(BaseModel):
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int
    
class MediaUploadResponseBody(ResponseBody):
    media_id: UUID
    status: str
    upload: MediaUploadInfo



