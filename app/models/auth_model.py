from pydantic import BaseModel

class RegisterRequestBody(BaseModel):
    email: str
    password: str
    username: str

class LoginRequestBody(BaseModel):
    email: str
    password: str