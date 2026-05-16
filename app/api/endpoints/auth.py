from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DBSession
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
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


@router.post("/refresh")
async def refresh_token_endpoint(body: RefreshRequest, db: DBSession) -> dict:
    access_token = await auth_service.refresh_access_token(db, body.refresh_token)
    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "token_type": "bearer",
        },
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout_endpoint(body: LogoutRequest, db: DBSession) -> dict:
    await auth_service.logout_user(db, body.refresh_token)
    await db.commit()
    return {"success": True, "message": "Logged out successfully."}


@router.get("/me")
async def me_endpoint(current_user: CurrentUser) -> dict:
    return {
        "success": True,
        "data": {
            "id": str(current_user.id),
            "email": current_user.email,
            "plan": current_user.plan.value
            if hasattr(current_user.plan, "value")
            else current_user.plan,
            "is_admin": current_user.is_admin,
            "is_super_admin": current_user.is_super_admin,
            "email_verified": current_user.email_verified,
            "created_at": current_user.created_at.isoformat(),
        },
    }
