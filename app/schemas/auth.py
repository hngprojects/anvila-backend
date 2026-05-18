import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


def check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return check_password(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return check_password(v)


class LoginData(BaseModel):
    user: UserResponse
    tokens: TokenResponse


class MeResponse(BaseModel):
    id: str
    email: str
    plan: str
    is_admin: bool
    is_super_admin: bool
    email_verified: bool
    created_at: str

    model_config = {"from_attributes": True}


class RefreshData(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LinkConfirmationData(BaseModel):
    link_confirmation_required: bool = True
    email_destination_hint: str


class OTTExchangeRequest(BaseModel):
    ott: str
