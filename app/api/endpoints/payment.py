import logging
from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.config import settings
from app.models.enums import PaymentStatus
from app.models.payment_transaction import PaymentTransaction
from app.schemas.payment import CheckoutResponse, PaymentStatusResponse, PaymentTransactionOut
from app.schemas.shared import ApiResponse

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payment", tags=["payment"])
AMOUNT_CENTS = 500  # $5.00
CURRENCY = "usd"


@router.post(
    "/checkout",
    summary="Create a Stripe Checkout session for private publishing",
    response_model=ApiResponse[CheckoutResponse],
)
async def create_checkout_session(
    current_user: CurrentUser,
    db: DBSession,
):
    # Already paid — no need to go through Stripe again
    existing = await db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.user_id == current_user.id,
            PaymentTransaction.status == PaymentStatus.SUCCEEDED,
        )
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "already_paid",
                "message": "You have already unlocked private publishing.",
            },
        )

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
        success_url=f"{settings.FRONTEND_URL}/settings/billing?status=success",
        cancel_url=f"{settings.FRONTEND_URL}/settings/billing?status=cancelled",
        client_reference_id=str(current_user.id),
        customer_email=current_user.email,
    )

    db.add(
        PaymentTransaction(
            user_id=current_user.id,
            stripe_session_id=session.id,
            amount_cents=AMOUNT_CENTS,
            currency=CURRENCY,
            status=PaymentStatus.PENDING,
        )
    )
    await db.commit()

    logger.info(
        "event=payment.checkout.created user_id=%s session_id=%s",
        current_user.id,
        session.id,
    )
    data = CheckoutResponse(checkout_url=session.url)
    return ApiResponse[CheckoutResponse](
        message="Stripe checkout session created",
        data=data,
    )


@router.post(
    "/webhook",
    summary="Stripe webhook handler",
    include_in_schema=False,
)
async def stripe_webhook(request: Request, db: DBSession):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError as e:
        logger.warning("event=payment.webhook.invalid_signature")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature") from e

    obj = event["data"]["object"]
    event_type = event["type"]
    logger.info("event=payment.webhook.received type=%s", event_type)

    if event_type == "checkout.session.completed":
        session_id = obj.get("id")
        intent_id = obj.get("payment_intent")
        amount = obj.get("amount_total", 0)
        currency = obj.get("currency", "usd")
        payment_status = obj.get("payment_status")  # "paid" or "unpaid"

        txn = await db.scalar(
            select(PaymentTransaction).where(PaymentTransaction.stripe_session_id == session_id)
        )
        if txn:
            txn.stripe_payment_intent_id = intent_id
            txn.amount_cents = amount
            txn.currency = currency
            txn.status = (
                PaymentStatus.SUCCEEDED if payment_status == "paid" else PaymentStatus.FAILED
            )
            txn.completed_at = datetime.now(UTC) if payment_status == "paid" else None
            await db.commit()
            logger.info(
                "event=payment.checkout.completed session_id=%s payment_status=%s",
                session_id,
                payment_status,
            )
        else:
            # Session not in our db — could be a replay or a direct Stripe dashboard charge
            logger.warning("event=payment.webhook.unmatched_session session_id=%s", session_id)

    elif event_type == "payment_intent.payment_failed":
        intent_id = obj.get("id")
        txn = await db.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.stripe_payment_intent_id == intent_id
            )
        )
        if txn:
            txn.status = PaymentStatus.FAILED
            await db.commit()
            logger.info("event=payment.intent.failed intent_id=%s", intent_id)

    return {"received": True}


@router.get(
    "/status",
    summary="Check if current user has paid for private publishing",
    response_model=PaymentStatusResponse,
)
async def payment_status(
    current_user: CurrentUser,
    db: DBSession,
):
    paid = await db.scalar(
        select(PaymentTransaction).where(
            PaymentTransaction.user_id == current_user.id,
            PaymentTransaction.status == PaymentStatus.SUCCEEDED,
        )
    )
    return PaymentStatusResponse(has_paid=paid is not None)


@router.get(
    "/transactions",
    summary="List current user's payment transactions",
    response_model=list[PaymentTransactionOut],
)
async def list_transactions(
    current_user: CurrentUser,
    db: DBSession,
):
    result = await db.scalars(
        select(PaymentTransaction)
        .where(PaymentTransaction.user_id == current_user.id)
        .order_by(PaymentTransaction.created_at.desc())
    )
    return result.all()
