from fastapi import APIRouter, Query

from app.api.deps import DBSession, PaginationParams
from app.schemas.explore import ExploreResponse
from app.schemas.shared import ApiResponse
from app.services.explore_service import fetch_explore

router = APIRouter(prefix="/explore", tags=["explore"])


@router.get("", response_model=ApiResponse[ExploreResponse])
async def explore(
    db: DBSession,
    params: PaginationParams,
    search: str | None = Query(None),
    category: str | None = Query(None),
):
    """
    Public persona registry. No auth required.
    Only returns published, public, listed, non-deleted personas.
    """
    data, meta = await fetch_explore(db=db, params=params, search=search, category=category)
    return ApiResponse[ExploreResponse](
        message="Personas retrieved successfully",
        data=data,
        meta=meta,
    )
