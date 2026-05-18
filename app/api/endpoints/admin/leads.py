from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AdminUser, DBSession, PaginationParams
from app.core.paginator import paginate
from app.models.contact import ContactMessage
from app.models.waitlist import WaitlistEntry
from app.schemas.leads import (
    ContactMessageRead,
    WaitlistEntryRead,
)
from app.schemas.shared import ApiResponse

router = APIRouter(prefix="/leads")


@router.get("/contacts", response_model=ApiResponse[list[ContactMessageRead]])
async def list_contacts(
    _: AdminUser,
    db: DBSession,
    page_params: PaginationParams,
):
    query = select(ContactMessage).order_by(ContactMessage.created_at.desc())
    rows, meta = await paginate(db, query, page_params)

    return ApiResponse(
        data=[ContactMessageRead.model_validate(r) for r in rows],
        meta=meta.model_dump(),
    )


@router.get("/waitlist", response_model=ApiResponse[list[WaitlistEntryRead]])
async def list_waitlist(
    _: AdminUser,
    db: DBSession,
    page_params: PaginationParams,
):
    query = select(WaitlistEntry).order_by(WaitlistEntry.created_at.desc())
    rows, meta = await paginate(db, query, page_params)

    return ApiResponse(
        data=[WaitlistEntryRead.model_validate(r) for r in rows],
        meta=meta.model_dump(),
    )
