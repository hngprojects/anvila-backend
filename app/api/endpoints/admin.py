import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import AdminUser, DBSession
from app.models.enums import UserPlan
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


class UpgradeUserRequest(BaseModel):
    user_id: uuid.UUID


@router.get("/dashboard")
async def admin_dashboard(current_user: AdminUser) -> dict:
    return {
        "success": True,
        "message": "Admin access confirmed.",
        "data": {
            "admin_email": current_user.email,
            "is_super_admin": current_user.is_super_admin,
        },
    }


@router.get("/me")
async def admin_me(current_user: AdminUser) -> dict:
    return {
        "success": True,
        "data": {
            "id": str(current_user.id),
            "email": current_user.email,
            "is_admin": current_user.is_admin,
            "is_super_admin": current_user.is_super_admin,
            "plan": current_user.plan.value
            if hasattr(current_user.plan, "value")
            else current_user.plan,
            "email_verified": current_user.email_verified,
            "created_at": current_user.created_at.isoformat(),
        },
    }


@router.post("/users/upgrade", status_code=status.HTTP_200_OK)
async def upgrade_user(body: UpgradeUserRequest, current_user: AdminUser, db: DBSession) -> dict:
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


@router.get("/users")
async def list_users(
    current_user: AdminUser,
    db: DBSession,
    plan: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    query = select(User)
    if plan is not None:
        query = query.where(User.plan == plan)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    users_result = await db.execute(
        query.order_by(User.created_at.desc()).limit(limit).offset(offset)
    )
    users = users_result.scalars().all()

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
        "total": total,
    }
