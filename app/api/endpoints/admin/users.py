"""Administrative user management endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AdminUser, DBSession, PaginationParams
from app.core.paginator import paginate
from app.models.enums import UserPlan
from app.models.user import User
from app.schemas.admin import AdminUserItem, UpgradeUserRequest, UpgradeUserResponse
from app.schemas.shared import ApiResponse

router = APIRouter(prefix="/users")


@router.post(
    "/upgrade",
    response_model=ApiResponse[UpgradeUserResponse],
    status_code=status.HTTP_200_OK,
)
async def upgrade_user(
    body: UpgradeUserRequest, _: AdminUser, db: DBSession
) -> ApiResponse[UpgradeUserResponse]:
    """Upgrade a user to paid plan while preserving the transition timestamp."""
    # Cheap unlocked fetch: handles the not-found and already-PAID cases without acquiring
    # a row lock.
    result = await db.execute(select(User).where(User.id == body.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.plan != UserPlan.PAID:
        # Re-fetch under a row lock and re-check inside the lock: serialises concurrent transitions.
        result = await db.execute(select(User).where(User.id == body.user_id).with_for_update())
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if user.plan != UserPlan.PAID:
            user.plan = UserPlan.PAID
            if user.upgraded_at is None:
                user.upgraded_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(user)

    plan_value = user.plan.value if hasattr(user.plan, "value") else user.plan
    return ApiResponse(
        data=UpgradeUserResponse(
            plan=plan_value,
            upgraded_at=user.upgraded_at,
        )
    )


@router.get("", response_model=ApiResponse[list[AdminUserItem]])
async def list_users(
    _: AdminUser,
    db: DBSession,
    page_params: PaginationParams,
    plan: UserPlan | None = Query(default=None),  # noqa: B008
) -> ApiResponse[list[AdminUserItem]]:
    """List users with optional plan filtering and pagination."""
    query = select(User).order_by(User.created_at.desc(), User.id.desc())
    if plan is not None:
        query = query.where(User.plan == plan)

    rows, meta = await paginate(db, query, page_params)
    users = list(rows)

    items = [
        AdminUserItem(
            id=str(user.id),
            email=user.email,
            plan=user.plan.value if hasattr(user.plan, "value") else user.plan,
            generation_count=user.generation_count,
            is_admin=user.is_admin,
            is_active=user.is_active,
            email_verified=user.email_verified,
            created_at=user.created_at,
        )
        for user in users
    ]
    return ApiResponse(data=items, meta=meta.model_dump())
