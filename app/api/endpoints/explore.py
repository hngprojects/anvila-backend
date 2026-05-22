from collections import defaultdict
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
        # Persona.is_listed == True,  # noqa
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
            # Persona.is_listed == True,  # noqa
            Persona.deleted_at == None,  # noqa
        )
        .distinct()
    )
    categories = sorted(c for c in all_cats_result.scalars().all() if c)

    persona_ids = [p.id for p in personas]
    skill_map: dict = defaultdict(list)
    if persona_ids:
        skills_result = await db.execute(
            select(PersonaSkill.persona_id, Skill.name)
            .join(Skill, PersonaSkill.skill_id == Skill.id)
            .where(PersonaSkill.persona_id.in_(persona_ids))
        )
        for persona_id, skill_name in skills_result.all():
            skill_map[persona_id].append(skill_name)

    result_personas = []
    for persona in personas:
        result_personas.append(
            ExplorePersona(
                id=persona.id,
                name=persona.name,
                description_summary=persona.description_summary,
                category=persona.category,
                github_repo_url=persona.github_repo_url,
                published_at=persona.published_at,
                skill_names=skill_map.get(persona.id, []),
            )
        )

    return ApiResponse[ExploreResponse](
        message="Personas retrieved successfully",
        data=ExploreResponse(personas=result_personas, categories=categories),
        meta=meta.model_dump(),
    )
