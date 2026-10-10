from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, PlainSerializer, TypeAdapter,
)

_datetime_adapter = TypeAdapter(datetime)


def _validate_timestamp(value):
    if isinstance(value, str):
        _datetime_adapter.validate_python(value)
    return value


def _timestamp_json(value):
    # Preserve JSONB strings and the existing ISO format for DB datetimes.
    return value.isoformat() if isinstance(value, datetime) else value


Timestamp = Annotated[
    datetime | str,
    BeforeValidator(_validate_timestamp),
    PlainSerializer(_timestamp_json, return_type=str, when_used="json"),
]


class ResponseBody(BaseModel):
    """Explicit response fields exclude private database columns."""

    model_config = ConfigDict(extra="ignore")


class PaginationResponseBody(ResponseBody):
    limit: int
    has_more: bool
    next_cursor: str | None


class ErrorResponseBody(ResponseBody):
    # Existing business errors may supply additional public error metadata.
    model_config = ConfigDict(extra="allow")

    error: str | None = None
    message: str | None = None
    timestamp: str | None = None
    details: list[dict[str, Any]] | None = None
