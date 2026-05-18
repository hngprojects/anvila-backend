from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class WaitlistEntry(BaseModel):
    __tablename__ = "waitlist_entries"

    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False)
