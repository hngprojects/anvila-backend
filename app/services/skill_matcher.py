from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill


async def match_skills(
    suggested_slugs: list[str],
    category: str,
    db: AsyncSession,
) -> list[Skill]:
    # For each slug in suggested_slugs:
    #   Try skills.sh API (GET {settings.SKILLSH_API_BASE}/skills/{slug})
    #   On success: upsert the skill into local skills table,
    #     set source_registry = SkillSourceRegistry.SKILLS_SH
    #   On failure (any exception, 404, timeout):
    #     query local skills table for the slug
    #     if found: include it
    #     if not found: skip
    #
    # After processing all slugs:
    #   Count resolved skills
    #   If count < 2:
    #     Query skills table for active seeded skills in the given category:
    #       WHERE category = category
    #       AND is_active = True
    #       AND source_registry = SkillSourceRegistry.ANVILA
    #       LIMIT (2 - count)
    #     Append these to the results
    #
    # Return the final list (2-6 Skill objects).
    raise NotImplementedError
