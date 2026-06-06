import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import PaymentStatus

if TYPE_CHECKING:
    from app.models.user import User


class PaymentTransaction(BaseModel):
    __tablename__ = "payment_transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    status: Mapped[PaymentStatus] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.PENDING
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationship
    user: Mapped["User"] = relationship(back_populates="payment_transactions")
