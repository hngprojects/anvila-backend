import re

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, DBSession
from app.models.enums import SkillSourceRegistry
from app.models.skill import Skill
from app.schemas.shared import ApiResponse, ErrorDetail
from app.schemas.skill import SkillCreateRequest, SkillRead, SkillUpdateRequest
from app.services.skill_sync import sync_skills_from_registry

router = APIRouter(prefix="/skills")


@router.post("/sync", response_model=ApiResponse)
async def sync_skills(
    user: AdminUser,
    category: str | None = None,
    limit: int | None = None,
) -> ApiResponse:
    """Synchronise skills from the external openclaw registry."""
    result = await sync_skills_from_registry(category=category, limit=limit)

    return ApiResponse(
        success=True,
        message="Skills synced successfully",
        data=result,
    )


@router.post("", response_model=ApiResponse[SkillRead], status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreateRequest,
    db: DBSession,
    user: AdminUser,
) -> ApiResponse[SkillRead]:
    """Create a manually seeded Anvila skill."""
    slug = body.slug.strip().lower()

    # Validate slug format (alphanumeric and hyphens only, non-empty)
    if not slug or not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorDetail(
                message="Slug must contain only lowercase letters, numbers and hyphens",
                code=status.HTTP_400_BAD_REQUEST,
                field="slug",
            ).model_dump(),
        )

    existing = await db.execute(select(Skill).where(Skill.slug == slug))
    if existing.scalar_one_or_none():
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ErrorDetail(
                message="Skill slug already exists",
                code=status.HTTP_409_CONFLICT,
                field="slug",
            ).model_dump(),
        )

    skill = Skill(
        slug=slug,
        name=body.name,
        description=body.description or "",
        content=body.content,
        category=body.category,
        tags=body.tags,
        source_registry=SkillSourceRegistry.ANVILA,
        is_active=True,
    )

    db.add(skill)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ErrorDetail(
                message="Skill slug already exists",
                code=status.HTTP_409_CONFLICT,
                field="slug",
            ).model_dump(),
        )
    await db.refresh(skill)

    return ApiResponse[SkillRead](
        success=True, message="Skill created successfully", data=SkillRead.model_validate(skill)
    )


@router.put("/{slug}", response_model=ApiResponse[SkillRead])
async def update_skill(
    slug: str,
    body: SkillUpdateRequest,
    db: DBSession,
    user: AdminUser,
) -> ApiResponse[SkillRead]:
    """Update an existing skill. Slug is immutable."""
    result = await db.execute(select(Skill).where(Skill.slug == slug))
    skill = result.scalar_one_or_none()

    if skill is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorDetail(
                message="Skill not found",
                code=status.HTTP_404_NOT_FOUND,
                field="slug",
            ).model_dump(),
        )

    if body.name is not None:
        skill.name = body.name

    if body.description is not None:
        skill.description = body.description

    if body.content is not None:
        skill.content = body.content

    if body.category is not None:
        skill.category = body.category

    if body.tags is not None:
        skill.tags = body.tags

    await db.commit()
    await db.refresh(skill)

    return ApiResponse[SkillRead](
        success=True,
        message=f"Skill {slug} updated successfully",
        data=SkillRead.model_validate(skill),
    )


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    slug: str,
    db: DBSession,
    user: AdminUser,
) -> None:
    """Soft-delete a skill by setting is_active to false."""
    result = await db.execute(select(Skill).where(Skill.slug == slug))
    skill = result.scalar_one_or_none()

    if skill is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorDetail(
                message="Skill not found",
                code=status.HTTP_404_NOT_FOUND,
                field="slug",
            ).model_dump(),
        )

    skill.is_active = False
    await db.commit()
