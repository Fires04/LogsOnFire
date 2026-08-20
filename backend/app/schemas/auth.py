from __future__ import annotations

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False


class MeResponse(BaseModel):
    id: str
    email: str
    is_admin: bool
