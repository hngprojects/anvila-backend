from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.models.enums import UserPlan

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(current_user: CurrentUser) -> dict:
    return {
        "id": str(current_user.id),
        "plan": current_user.plan.value if hasattr(current_user.plan, "value") else current_user.plan,
        "generation_count": current_user.generation_count,
        "generation_limit": 3 if current_user.plan == UserPlan.FREE else None,
        "refine_used": current_user.refine_used,
        "github_connected": current_user.github_connected,
        "github_username": current_user.github_username,
        "total_tokens_used": current_user.total_tokens_used,
    }
