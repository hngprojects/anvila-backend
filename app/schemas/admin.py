"""Schemas for administrative user management requests."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class UpgradeUserRequest(BaseModel):
    user_id: uuid.UUID


class UpgradeUserResponse(BaseModel):
    plan: str
    upgraded_at: datetime | None


class AdminUserItem(BaseModel):
    id: str
    email: str
    plan: str
    generation_count: int
    is_admin: bool
    is_active: bool
    email_verified: bool
    created_at: datetime
