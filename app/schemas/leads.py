from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class ContactMessageCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str | None = None
    message: str


class ContactMessageRead(BaseModel):
    id: UUID
    full_name: str
    email: str
    phone: str | None
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WaitlistEntryCreate(BaseModel):
    full_name: str
    email: EmailStr


class WaitlistEntryRead(BaseModel):
    id: UUID
    full_name: str
    email: str
    is_notified: bool
    created_at: datetime

    model_config = {"from_attributes": True}
