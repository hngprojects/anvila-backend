import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionSummary(BaseModel):
    session_id: uuid.UUID
    persona_id: uuid.UUID
    persona_name: str | None
    last_message_preview: str | None
    last_message_at: datetime | None
    status: str


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    round_number: int
    created_at: datetime
