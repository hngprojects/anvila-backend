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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> ApiResponse[list[SkillRead]]:
    """Return active skills from the local skill catalog."""

    offset = (page - 1) * page_size

    skills, total = await list_skills(
        db,
        search=search,
        category=category,
        limit=page_size,
        offset=offset,
    )

    total_pages = (total + page_size - 1) // page_size

    return ApiResponse[list[SkillRead]](
        success=True,
        message="Skills retrieved successfully",
        data=[SkillRead.model_validate(skill) for skill in skills],
        meta={
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        },
    )
