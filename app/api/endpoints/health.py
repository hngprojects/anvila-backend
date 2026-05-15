from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DBSession

router = APIRouter()


@router.get("/health")
async def health(db: DBSession) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
