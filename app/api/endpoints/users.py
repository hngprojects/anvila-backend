"""Current user account inspection endpoints."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.models.enums import UserPlan
from app.schemas.shared import ApiResponse
from app.schemas.users import UserMeResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=ApiResponse[UserMeResponse])
async def get_me(current_user: CurrentUser) -> ApiResponse[UserMeResponse]:
    """Return the authenticated user's account and usage metadata."""
    plan = current_user.plan.value if hasattr(current_user.plan, "value") else current_user.plan
    return ApiResponse(
        data=UserMeResponse(
            id=str(current_user.id),
            plan=plan,
            generation_count=current_user.generation_count,
            generation_limit=3 if plan == UserPlan.FREE.value else None,
            refine_used=current_user.refine_used,
            github_connected=current_user.github_connected,
            github_username=current_user.github_username,
            total_tokens_used=current_user.total_tokens_used,
        )
    )
