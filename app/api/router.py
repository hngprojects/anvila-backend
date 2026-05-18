from fastapi import APIRouter

from app.api.endpoints import auth, health
from app.api.endpoints.admin import router as admin_router
from app.api.endpoints.users import router as users_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(admin_router)
api_router.include_router(users_router)
