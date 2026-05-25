"""Administrative user management endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AdminUser, DBSession, PaginationParams
from app.core.paginator import paginate
from app.models.enums import UserPlan
from app.models.user import User
from app.schemas.admin import UpgradeUserRequest

router = APIRouter(prefix="/users")


@router.post("/upgrade", status_code=status.HTTP_200_OK)
async def upgrade_user(body: UpgradeUserRequest, _: AdminUser, db: DBSession) -> dict:
    """Upgrade a user to paid plan while preserving the transition timestamp."""
    result = await db.execute(select(User).where(User.id == body.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.plan != UserPlan.PAID:
        user.plan = UserPlan.PAID
        user.upgraded_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(user)

    return {
        "plan": user.plan.value if hasattr(user.plan, "value") else user.plan,
        "upgraded_at": user.upgraded_at.isoformat() if user.upgraded_at else None,
    }


@router.get("")
async def list_users(
    _: AdminUser,
    db: DBSession,
    page_params: PaginationParams,
    plan: UserPlan | None = Query(default=None),  # noqa: B008
) -> dict:
    """List users with optional plan filtering and pagination."""
    query = select(User).order_by(User.created_at.desc())
    if plan is not None:
        query = query.where(User.plan == plan)

    rows, meta = await paginate(db, query, page_params)
    users = list(rows)

    return {
        "users": [
            {
                "id": str(user.id),
                "email": user.email,
                "plan": user.plan.value if hasattr(user.plan, "value") else user.plan,
                "generation_count": user.generation_count,
                "is_admin": user.is_admin,
                "is_active": user.is_active,
                "email_verified": user.email_verified,
                "created_at": user.created_at.isoformat(),
            }
            for user in users
        ],
        "total": meta.total,
    }
