from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.common import (
    PaginationResponseBody, ResponseBody, Timestamp,
)
from app.models.user_model import UserPageQuery, UserSummaryResponseBody


class SendFriendRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


class RespondFriendRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_at: datetime

    @field_validator("requested_at", mode="before")
    @classmethod
    def validate_timestamp_format(cls, value):
        if isinstance(value, str):
            if re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
                r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
                value,
            ) is None:
                raise ValueError(
                    "requested_at must be an ISO timestamp with a timezone"
                )
        elif not isinstance(value, datetime):
            raise ValueError("requested_at must be a timestamp")
        return value

    @field_validator("requested_at")
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include a timezone")
        return value


class FriendRequestsQuery(UserPageQuery):
    direction: Literal["incoming", "outgoing"] = "incoming"


class FriendRequestsCursor(RespondFriendRequestBody):
    id: UUID


class FriendRequestResponseBody(ResponseBody):
    peer: UserSummaryResponseBody
    requester_id: UUID
    recipient_id: UUID
    status: Literal["PENDING", "ACCEPTED", "REJECTED", "CANCELLED", "REMOVED"]
    requested_at: Timestamp
    responded_at: Timestamp | None
    updated_at: Timestamp


class FriendRequestsResponseBody(ResponseBody):
    data: list[FriendRequestResponseBody]
    pagination: PaginationResponseBody
