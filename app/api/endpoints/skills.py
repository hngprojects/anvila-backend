from fastapi import APIRouter, Query

from app.api.deps import DBSession
from app.schemas.shared import ApiResponse
from app.schemas.skill import SkillRead
from app.services.skill_query import list_skills

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=ApiResponse[list[SkillRead]])
async def get_skills(
    db: DBSession,
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ApiResponse[list[SkillRead]]:
    """Return active skills from the local skill catalog."""

    skills, total = await list_skills(
        db,
        search=search,
        category=category,
        limit=limit,
        offset=offset,
    )

    return ApiResponse[list[SkillRead]](
        success=True,
        message="Skills retrieved successfully",
        data=[SkillRead.model_validate(skill) for skill in skills],
        meta={
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    )