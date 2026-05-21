from fastapi import APIRouter

from app.api.endpoints import auth, chat, explore, health, leads, personas, skills
from app.api.endpoints.admin import router as admin_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(explore.router)
api_router.include_router(leads.router)
api_router.include_router(admin_router.api_router)
api_router.include_router(personas.router)
api_router.include_router(skills.router)