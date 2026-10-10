from uuid import UUID

from app.models.common import ResponseBody, Timestamp


class MediaResponseBody(ResponseBody):
    id: UUID
    content_type: str | None = None
    byte_size: int | None = None
    width: int | None = None
    height: int | None = None
    status: str | None = None
    created_at: Timestamp | None = None
    download_url: str | None = None
    url_expires_at: Timestamp | None = None
