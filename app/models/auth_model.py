from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.common import ResponseBody, Timestamp


class RegisterRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    password: str
    username: str


class LoginRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    password: str


class RegisterResponseBody(ResponseBody):
    message: str
    user_id: UUID
    timestamp: Timestamp


class LoginUserResponseBody(ResponseBody):
    id: UUID
    email: str


class LoginResponseBody(ResponseBody):
    message: str
    user: LoginUserResponseBody
    access_token: str
    refresh_token: str
    session_id: UUID
    expires_at: Timestamp
    timestamp: Timestamp


class AccessTokenResponseBody(ResponseBody):
    access_token: str


class LogoutResponseBody(ResponseBody):
    message: str
