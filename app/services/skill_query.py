from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill


async def list_skills(
    db: AsyncSession,
    *,
    search: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Skill], int]:
    """List active skills with optional search and category filtering."""
    filters = [Skill.is_active.is_(True)]

    if category:
        filters.append(Skill.category == category)

    if search:
        pattern = f"%{search}%"
        filters.append(
            or_(
                Skill.name.ilike(pattern),
                Skill.description.ilike(pattern),
            )
        )

    total_result = await db.execute(
        select(func.count()).select_from(Skill).where(*filters)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Skill)
        .where(*filters)
        .order_by(Skill.name.asc())
        .limit(limit)
        .offset(offset)
    )

    return list(result.scalars().all()), total