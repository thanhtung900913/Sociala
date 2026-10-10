from typing import Literal
from uuid import UUID

from pydantic import Field

from app.models.common import PaginationResponseBody, ResponseBody, Timestamp
from app.models.media_model import MediaResponseBody
from app.models.user_model import UserSummaryResponseBody

ReactionType = Literal["LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY"]


class AttachmentResponseBody(ResponseBody):
    position: int
    alt_text: str | None
    media: MediaResponseBody


class PostCountsResponseBody(ResponseBody):
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    by_reaction: dict[ReactionType, int]


class PostResponseBody(ResponseBody):
    id: UUID
    content: str | None
    visibility: str
    kind: Literal["ORIGINAL", "SHARE"]
    shared_post_id: UUID | None
    created_at: Timestamp
    updated_at: Timestamp
    author: UserSummaryResponseBody
    attachments: list[AttachmentResponseBody] = Field(default_factory=list)
    counts: PostCountsResponseBody
    my_reaction: ReactionType | None = None
    original_post: "PostResponseBody | None" = None


class PostsResponseBody(ResponseBody):
    data: list[PostResponseBody]
    pagination: PaginationResponseBody
