from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select

from app.api.deps import DBSession
from app.email.sender import send_contact_admin_notification
from app.models.contact import ContactMessage
from app.models.waitlist import WaitlistEntry
from app.schemas.leads import (
    ContactMessageCreate,
    ContactMessageRead,
    WaitlistEntryCreate,
    WaitlistEntryRead,
)
from app.schemas.shared import ApiResponse

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post(
    "/contact",
    response_model=ApiResponse[ContactMessageRead],
    status_code=status.HTTP_201_CREATED,
)
async def submit_contact(
    payload: ContactMessageCreate,
    db: DBSession,
    bg_task: BackgroundTasks,
):
    entry = ContactMessage(**payload.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    bg_task.add_task(
        send_contact_admin_notification,
        entry.full_name,
        entry.email,
        entry.message,
        entry.phone,
    )

    return ApiResponse(
        message="Your message has been received. We'll be in touch soon.",
        data=ContactMessageRead.model_validate(entry),
    )


@router.post(
    "/waitlist",
    response_model=ApiResponse[WaitlistEntryRead],
    status_code=status.HTTP_201_CREATED,
)
async def join_waitlist(payload: WaitlistEntryCreate, db: DBSession):
    existing = await db.scalar(select(WaitlistEntry).where(WaitlistEntry.email == payload.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already on the waitlist."
        )

    entry = WaitlistEntry(**payload.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return ApiResponse(
        message="You're on the waitlist! We'll notify you when we launch.",
        data=WaitlistEntryRead.model_validate(entry),
    )
