from uuid import UUID
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.user.models.common import PaginationResponseBody, ResponseBody, Timestamp


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: UUID
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    media_ids: list[UUID] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def require_content(self):
        if not self.body and not self.media_ids:
            raise ValueError("body or media_ids is required")
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("media_ids must be unique")
        return self


class MessagePageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class MessageSyncQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_seq: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=100)


class MessageResponse(ResponseBody):
    id: UUID
    conversation_id: UUID
    sender: dict[str, Any] | None
    seq: int
    client_message_id: UUID
    body: str | None
    attachments: list[dict[str, Any]]
    is_deleted: bool
    created_at: Timestamp
    updated_at: Timestamp


class MessagePageResponse(ResponseBody):
    data: list[MessageResponse]
    pagination: PaginationResponseBody