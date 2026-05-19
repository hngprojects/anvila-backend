import math
from typing import Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class PageParams:
    """Inject this as a dependency in any endpoint that needs pagination."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number, 1-indexed"),
        size: int = Query(20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.size = size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


class PaginatedMeta(BaseModel):
    page: int
    size: int
    total: int
    pages: int
    has_next: bool
    has_prev: bool


async def paginate(
    db: AsyncSession,
    query: Select,
    params: PageParams,
) -> tuple[Any, PaginatedMeta]:
    """
    Run a count + paginated fetch against any SQLAlchemy select query.
    """
    count_query = select(func.count()).select_from(query.subquery())
    total: int = await db.scalar(count_query) or 0

    total_pages = math.ceil(total / params.size) if total else 1

    rows = await db.scalars(query.offset(params.offset).limit(params.limit))

    meta = PaginatedMeta(
        page=params.page,
        size=params.size,
        total=total,
        pages=total_pages,
        has_next=params.page < total_pages,
        has_prev=params.page > 1,
    )

    return rows, meta
