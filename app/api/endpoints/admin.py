from fastapi import APIRouter

from app.api.deps import AdminUser

router = APIRouter(prefix="/admin", tags=["admin"])


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


@router.get("/users/me")
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
