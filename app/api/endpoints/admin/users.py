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
async def upgrade_user(
    body: UpgradeUserRequest, _: AdminUser, db: DBSession
) -> dict:
    result = await db.execute(select(User).where(User.id == body.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.plan = UserPlan.PAID
    user.upgraded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)

    return {
        "plan": user.plan.value if hasattr(user.plan, "value") else user.plan,
        "upgraded_at": user.upgraded_at.isoformat(),
    }


@router.get("")
async def list_users(
    _: AdminUser,
    db: DBSession,
    page_params: PaginationParams,
    plan: UserPlan | None = Query(default=None),  # noqa: B008
) -> dict:
    query = select(User).order_by(User.created_at.desc())
    if plan is not None:
        query = query.where(User.plan == plan)

    rows, meta = await paginate(db, query, page_params)
    users = list(rows)

    return {
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "plan": u.plan.value if hasattr(u.plan, "value") else u.plan,
                "generation_count": u.generation_count,
                "is_admin": u.is_admin,
                "is_active": u.is_active,
                "email_verified": u.email_verified,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
        "total": meta.total,
    }
