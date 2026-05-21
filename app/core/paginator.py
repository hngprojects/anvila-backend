import math
import uuid
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, and_, func, inspect, or_, select
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


class CursorParams:
    """
    Inject as a dependency in any endpoint that needs cursor pagination.
    """

    def __init__(
        self,
        cursor: Annotated[
            uuid.UUID | None,
            Query(description="UUID of the last item received. Omit for the first page."),
        ] = None,
        size: Annotated[int, Query(ge=1, le=50, description="Items per page (max 50)")] = 20,
    ):
        self.cursor = cursor
        self.size = size


class CursorMeta(BaseModel):
    size: int
    has_more: bool
    # The cursor the client should send to get the next page.
    # None when there are no more items.
    next_cursor: uuid.UUID | None


async def cursor_paginate(
    db: AsyncSession,
    query: Select,
    params: CursorParams,
    model: type,
    cursor_field: str,
    descending: bool = True,
) -> tuple[list[Any], CursorMeta]:
    """
    Cursor-based pagination with a composite keyset (sort_col, pk).

    Safe for nullable sort values and duplicate sort values.
    """
    sort_col = getattr(model, cursor_field)

    # Resolve the primary key column name (assumes single-column PK).
    pk_attr = inspect(model).primary_key[0].name
    pk_col = getattr(model, pk_attr)

    if params.cursor:
        cursor_record = await db.get(model, params.cursor)
        if cursor_record:
            cursor_value = getattr(cursor_record, cursor_field)
            cursor_id = getattr(cursor_record, pk_attr)

            if descending:
                if cursor_value is None:
                    query = query.where(and_(sort_col.is_(None), pk_col < cursor_id))
                else:
                    query = query.where(
                        or_(
                            sort_col < cursor_value,
                            and_(sort_col == cursor_value, pk_col < cursor_id),
                            sort_col.is_(None),
                        )
                    )
            else:
                if cursor_value is None:
                    query = query.where(
                        or_(
                            and_(sort_col.is_(None), pk_col > cursor_id),
                            sort_col.isnot(None),
                        )
                    )
                else:
                    query = query.where(
                        or_(
                            sort_col > cursor_value,
                            and_(sort_col == cursor_value, pk_col > cursor_id),
                        )
                    )

    if descending:
        ordered_query = query.order_by(
            sort_col.desc().nulls_last(),
            pk_col.desc(),
        )
    else:
        ordered_query = query.order_by(
            sort_col.asc().nulls_first(),
            pk_col.asc(),
        )

    result = await db.scalars(ordered_query.limit(params.size + 1))
    rows = result.all()

    has_more = len(rows) > params.size
    items = list(rows[: params.size])

    next_cursor = getattr(items[-1], pk_attr) if has_more and items else None

    meta = CursorMeta(
        size=params.size,
        has_more=has_more,
        next_cursor=next_cursor,
    )
    return items, meta
