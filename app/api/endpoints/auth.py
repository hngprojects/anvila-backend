from fastapi import APIRouter, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DBSession) -> UserResponse:
    user = await auth_service.register_user(
        db,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: DBSession) -> LoginResponse:
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    access_token, raw_refresh = await auth_service.login_user(
        db,
        email=body.email,
        password=body.password,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    await db.commit()

    result = await auth_service.get_user_by_email(db, body.email)
    return LoginResponse(
        user=UserResponse.model_validate(result),
        tokens=TokenResponse(access_token=access_token, refresh_token=raw_refresh),
    )
