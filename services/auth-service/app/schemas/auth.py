from datetime import datetime

from pydantic import BaseModel
from typing import Literal


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role_code: Literal["nurse", "doctor", "admin"] = "nurse"
    phone: str | None = None


class UserOut(BaseModel):
    id: str
    full_name: str
    role_code: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime
    user: UserOut


class RegisterResponse(BaseModel):
    ok: bool = True
    user: UserOut
