"""Schemas for administrative user management requests."""

import uuid

from pydantic import BaseModel


class UpgradeUserRequest(BaseModel):
    user_id: uuid.UUID
