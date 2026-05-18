from fastapi import APIRouter

from .leads import router as leads_router

api_router = APIRouter(prefix="/admin", tags=["admin"])
api_router.include_router(leads_router)
