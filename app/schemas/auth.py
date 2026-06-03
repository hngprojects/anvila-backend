import re
import uuid
from datetime import datetime

import bleach
from pydantic import BaseModel, EmailStr, Field, field_validator


def check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


# removes dangerous HTML tags and attributes
def sanitize_display_name(v: str) -> str:
    stripped = bleach.clean(v, tags=[], attributes={}, strip=True)
    stripped = " ".join(stripped.split())
    if not stripped:
        raise ValueError("Display name cannot be empty or contain only markup")
    return stripped


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = Field(default=None, min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return check_password(v)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return sanitize_display_name(v)


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
    display_name: str | None
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
