from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DBSession
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    ResendVerificationRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.services import auth as auth_service
from app.services.email import send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DBSession) -> UserResponse:
    user, verification_url = await auth_service.register_user(
        db,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    await db.refresh(user)
    await send_verification_email(user.email, verification_url)
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


@router.post("/verify-email", response_model=UserResponse)
async def verify_email(body: VerifyEmailRequest, db: DBSession) -> UserResponse:
    user = await auth_service.verify_email(db, body.token)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification(body: ResendVerificationRequest, db: DBSession) -> None:
    verification_url = await auth_service.resend_verification_email(db, body.email)
    await db.commit()
    if verification_url:
        await send_verification_email(body.email, verification_url)
