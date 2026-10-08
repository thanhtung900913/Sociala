from datetime import date, datetime, timezone
import re
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator, model_validator
)


class UpdateUserRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_]{3,30}$")


class DeleteUserRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    confirmation: Literal["DELETE_MY_ACCOUNT"]


class UserPageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class SearchUsersQuery(UserPageQuery):
    q: str = Field(min_length=2, max_length=50)

    @field_validator("q", mode="before")
    @classmethod
    def normalize_search(cls, value):
        if isinstance(value, str):
            return " ".join(value.split()).lower()
        return value


class SearchUsersCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=30, pattern=r"^[a-z0-9_]{3,30}$")
    id: UUID


class UserPostsCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    id: UUID

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError("Cursor timestamp must include a timezone")
        return value


class UpdateProfileRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=500)
    birthday: date | None = None
    gender: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=150)
    website: str | None = Field(default=None, max_length=2048)
    avatar_media_id: UUID | None = None
    cover_media_id: UUID | None = None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value):
        if value is None or not value.strip():
            raise ValueError("Display name must not be null or blank")
        return value.strip()

    @field_validator("birthday", mode="before")
    @classmethod
    def validate_birthday(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            value = date.fromisoformat(value)
        elif type(value) is not date:
            raise ValueError("Birthday must use YYYY-MM-DD format")
        if value > datetime.now(timezone.utc).date():
            raise ValueError("Birthday must not be in the future")
        return value

    @field_validator("website")
    @classmethod
    def validate_website(cls, value):
        if value is None:
            return None
        if not value.startswith(("http://", "https://")) or any(
            character.isspace() for character in value
        ):
            raise ValueError("Website must be an HTTP/HTTPS URL")
        url = str(TypeAdapter(HttpUrl).validate_python(value))
        if len(url) > 2048:
            raise ValueError("Website must not exceed 2048 characters")
        return url

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        return self
