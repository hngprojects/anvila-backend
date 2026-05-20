from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select

from app.api.deps import DBSession
from app.core.paginator import PageParams, paginate
from app.models.enums import PersonaStatus, PersonaVisibility
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.schemas.explore import ExplorePersona, ExploreResponse
from app.schemas.shared import ApiResponse

router = APIRouter(prefix="/explore", tags=["explore"])


@router.get("", response_model=ApiResponse[ExploreResponse])
async def explore(
    db: DBSession,
    params: Annotated[PageParams, Depends()],
    search: str | None = Query(None),
    category: str | None = Query(None),
):
    """
    Public persona registry. No auth required.
    Only returns published, public, listed, non-deleted personas.
    """
    filters = [
        Persona.visibility == PersonaVisibility.PUBLIC,
        Persona.status == PersonaStatus.PUBLISHED,
        Persona.is_listed == True,  # noqa
        Persona.deleted_at == None,  # noqa
    ]
    if search:
        term = f"%{search}%"
        filters.append(
            or_(
                Persona.name.ilike(term),
                Persona.description_summary.ilike(term),
            )
        )
    if category:
        filters.append(func.lower(Persona.category) == category.lower())

    query = select(Persona).where(and_(*filters)).order_by(Persona.published_at.desc())

    rows, meta = await paginate(db, query, params)
    personas = rows.all()

    all_cats_result = await db.execute(
        select(Persona.category)
        .where(
            Persona.visibility == PersonaVisibility.PUBLIC,
            Persona.status == PersonaStatus.PUBLISHED,
            Persona.is_listed == True,  # noqa
            Persona.deleted_at == None,  # noqa
        )
        .distinct()
    )
    categories = sorted(c for c in all_cats_result.scalars().all() if c)

    result_personas = []
    for persona in personas:
        skills_result = await db.execute(
            select(Skill.name)
            .join(PersonaSkill, PersonaSkill.skill_id == Skill.id)
            .where(PersonaSkill.persona_id == persona.id)
        )
        result_personas.append(
            ExplorePersona(
                id=persona.id,
                name=persona.name,
                description_summary=persona.description_summary,
                category=persona.category,
                github_repo_url=persona.github_repo_url,
                published_at=persona.published_at,
                skill_names=list(skills_result.scalars().all()),
            )
        )

    return ApiResponse[ExploreResponse](
        message="Personas retrieved successfully",
        data=ExploreResponse(personas=result_personas, categories=categories),
        meta=meta.model_dump(),
    )
