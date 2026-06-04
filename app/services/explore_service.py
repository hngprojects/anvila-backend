from collections import defaultdict

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PageParams
from app.core.cache import explore_cache
from app.core.paginator import PaginatedMeta, paginate
from app.models.enums import PersonaCategory, PersonaStatus, PersonaVisibility
from app.models.persona import Persona
from app.models.persona_skill import PersonaSkill
from app.models.skill import Skill
from app.schemas.explore import ExplorePersona, ExploreResponse


def _explore_cache_key(page: int, size: int, search: str | None, category: str | None) -> dict:
    return {
        "endpoint": "explore",
        "page": page,
        "size": size,
        "search": search,
        "category": category.lower() if category else None,
    }


async def fetch_explore(
    db: AsyncSession,
    params: PageParams,
    search: str | None,
    category: str | None,
) -> tuple[ExploreResponse, dict]:
    # return early if category does not exist
    category_enum: PersonaCategory | None = None
    if category:
        try:
            category_enum = PersonaCategory(category.lower())
        except ValueError:
            return ExploreResponse(personas=[], categories=[]), PaginatedMeta(
                page=params.page, size=params.size, total=0, pages=1, has_next=False, has_prev=False
            ).model_dump()

    cache_key = _explore_cache_key(params.page, params.size, search, category)

    async def fetch() -> dict:
        filters = [
            Persona.visibility == PersonaVisibility.PUBLIC,
            Persona.status == PersonaStatus.PUBLISHED,
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

        if category_enum:
            filters.append(Persona.category == category_enum)

        query = select(Persona).where(and_(*filters)).order_by(Persona.published_at.desc())
        rows, meta = await paginate(db, query, params)
        personas = rows.all()

        all_cats_result = await db.execute(
            select(Persona.category)
            .where(
                Persona.visibility == PersonaVisibility.PUBLIC,
                Persona.status == PersonaStatus.PUBLISHED,
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

        result_personas = [
            ExplorePersona(
                id=persona.id,
                name=persona.name,
                description_summary=persona.description_summary,
                category=persona.category,
                github_repo_url=persona.github_repo_url,
                published_at=persona.published_at,
                skill_names=skill_map.get(persona.id, []),
            )
            for persona in personas
        ]
        return {
            "data": ExploreResponse(personas=result_personas, categories=categories).model_dump(),
            "meta": meta.model_dump(),
        }

    cached = await explore_cache.get_or_set(cache_key, fetch, ttl=60)
    return cached["data"], cached["meta"]
