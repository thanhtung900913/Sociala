from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, Field, field_validator, model_validator,
)

from app.models.common import PaginationResponseBody, ResponseBody, Timestamp
from app.models.media_model import MediaResponseBody
from app.models.user_model import (
    UserPageQuery, UserPostsCursor, UserSummaryResponseBody,
)

ReactionType = Literal["LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY"]
PostVisibility = Literal["PUBLIC", "FRIENDS", "PRIVATE"]


class AttachmentRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    alt_text: str | None = Field(default=None, max_length=500)


class SharePostRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=10000)
    visibility: PostVisibility = "PUBLIC"

    @field_validator("content")
    @classmethod
    def require_nonblank_content(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Content must not be blank")
        return value


class CreatePostRequestBody(SharePostRequestBody):
    attachments: list[AttachmentRequestBody] = Field(
        default_factory=list, max_length=10
    )

    @field_validator("attachments")
    @classmethod
    def require_unique_media(cls, value):
        if len({item.media_id for item in value}) != len(value):
            raise ValueError("Attachment media IDs must be unique")
        return value


class UpdatePostRequestBody(CreatePostRequestBody):
    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("At least one post field is required")
        return self


class PutReactionRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reaction_type: ReactionType


class CreateCommentRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=3000)
    parent_comment_id: UUID | None = None

    @field_validator("content")
    @classmethod
    def require_nonblank_content(cls, value):
        if not value.strip():
            raise ValueError("Content must not be blank")
        return value


class PostPageQuery(UserPageQuery):
    pass


class ReactionsQuery(PostPageQuery):
    reaction_type: ReactionType | None = None


class PostPageCursor(UserPostsCursor):
    pass


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


class PostMutationResponseBody(ResponseBody):
    id: UUID
    updated_at: Timestamp


class ReactionStateResponseBody(ResponseBody):
    post_id: UUID
    reaction_type: ReactionType
    counts: PostCountsResponseBody


class ReactionEntryResponseBody(ResponseBody):
    user: UserSummaryResponseBody
    reaction_type: ReactionType
    created_at: Timestamp


class ReactionsResponseBody(ResponseBody):
    data: list[ReactionEntryResponseBody]
    pagination: PaginationResponseBody


class CommentResponseBody(ResponseBody):
    id: UUID
    post_id: UUID
    author: UserSummaryResponseBody | None
    parent_comment_id: UUID | None
    content: str | None
    is_deleted: bool
    is_unavailable: bool
    reply_count: int
    like_count: int
    liked_by_me: bool
    created_at: Timestamp
    updated_at: Timestamp


class CommentsResponseBody(ResponseBody):
    data: list[CommentResponseBody]
    pagination: PaginationResponseBody
