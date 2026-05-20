from fastapi import APIRouter

from app.api.endpoints import auth, health, leads, personas
from app.api.endpoints.admin import router as admin_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(leads.router)
api_router.include_router(admin_router.api_router)
api_router.include_router(personas.router)
