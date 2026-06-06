from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import PaymentStatus


class CheckoutResponse(BaseModel):
    checkout_url: str | None


class PaymentStatusResponse(BaseModel):
    has_paid: bool


class PaymentTransactionOut(BaseModel):
    id: UUID
    stripe_session_id: str | None
    stripe_payment_intent_id: str | None
    amount_cents: int
    currency: str
    status: PaymentStatus
    completed_at: datetime | None

    model_config = {"from_attributes": True}
