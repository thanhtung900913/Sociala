from uuid import UUID
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.user.models.common import PaginationResponseBody, ResponseBody, Timestamp


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


class ConversationPageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class ConversationMemberResponse(ResponseBody):
    user_id: UUID
    last_read_seq: int | None
    last_read_at: Timestamp | None


class ConversationUserResponse(ResponseBody):
    id: UUID
    username: str
    display_name: str
    avatar_url: str | None = None


class ConversationResponse(ResponseBody):
    id: UUID
    peer: ConversationUserResponse | None
    members: list[ConversationMemberResponse]
    last_message_seq: int
    last_message: dict[str, Any] | None
    unread_count: int
    created_at: Timestamp
    updated_at: Timestamp


class ConversationPageResponse(ResponseBody):
    data: list[ConversationResponse]
    pagination: PaginationResponseBody