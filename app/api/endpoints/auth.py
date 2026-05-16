from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DBSession
from app.core.config import settings
from app.schemas.shared import ApiResponse
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginData,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshData,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.services import auth as auth_service
from app.services.email import send_password_reset_email, send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest, db: DBSession, bg_task: BackgroundTasks
) -> ApiResponse[UserResponse]:
    try:
        user, verification_url = await auth_service.register_user(
            db,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    await db.refresh(user)
    bg_task.add_task(send_verification_email, user.email, verification_url)

    return ApiResponse[UserResponse](
        message="Registration successful. Please check your email to verify your account.",
        data=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=ApiResponse[LoginData])
async def login(body: LoginRequest, request: Request, db: DBSession) -> ApiResponse[LoginData]:
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

    user = await auth_service.get_user_by_email(db, body.email)

    return ApiResponse[LoginData](
        message="Login successful.",
        data=LoginData(
            user=UserResponse.model_validate(user),
            tokens=TokenResponse(
                access_token=access_token,
                refresh_token=raw_refresh,
            ),
        ),
    )


@router.post("/verify-email", response_model=ApiResponse[UserResponse])
async def verify_email(body: VerifyEmailRequest, db: DBSession) -> ApiResponse[UserResponse]:
    user = await auth_service.verify_email(db, body.token)
    await db.commit()
    await db.refresh(user)

    return ApiResponse[UserResponse](
        message="Email verified successfully.",
        data=UserResponse.model_validate(user),
    )


@router.post("/resend-verification", response_model=ApiResponse[None])
async def resend_verification(
    body: ResendVerificationRequest, db: DBSession, bg_task: BackgroundTasks
) -> ApiResponse[None]:
    verification_url = await auth_service.resend_verification_email(db, body.email)
    await db.commit()

    if verification_url:
        bg_task.add_task(send_verification_email, body.email, verification_url)

    # Intentionally vague — never reveal whether the address exists
    return ApiResponse[None](
        message="If this email is registered and unverified, a new verification link has been sent.",
    )


@router.post("/refresh", response_model=ApiResponse[RefreshData])
async def refresh_token_endpoint(body: RefreshRequest, db: DBSession) -> ApiResponse[RefreshData]:
    access_token = await auth_service.refresh_access_token(db, body.refresh_token)

    return ApiResponse[RefreshData](
        message="Token refreshed.",
        data=RefreshData(access_token=access_token),
    )


@router.post("/logout", response_model=ApiResponse[None], status_code=status.HTTP_200_OK)
async def logout_endpoint(body: LogoutRequest, db: DBSession) -> ApiResponse[None]:
    await auth_service.logout_user(db, body.refresh_token)
    await db.commit()

    return ApiResponse[None](message="Logged out successfully.")


@router.post("/forgot-password", response_model=ApiResponse[None])
async def forgot_password(
    body: ForgotPasswordRequest, db: DBSession, bg_task: BackgroundTasks
) -> ApiResponse[None]:
    raw_token = await auth_service.create_password_reset_token(db, body.email)

    if raw_token:
        try:
            # Fragment (#) keeps the token out of server logs and Referer headers
            reset_url = f"{settings.FRONTEND_URL}/reset-password#token={raw_token}"
            bg_task.add_task(send_password_reset_email, body.email, reset_url)
        except Exception:
            pass  # Never surface email-sending failures to the caller

    # Intentionally vague — never reveal whether the email exists or has a password account
    return ApiResponse[None](
        message="If this email exists and has a password account, a reset link has been sent.",
    )


@router.post("/reset-password", response_model=ApiResponse[None])
async def reset_password_endpoint(body: ResetPasswordRequest, db: DBSession) -> ApiResponse[None]:
    success = await auth_service.reset_password(db, body.token, body.new_password)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    return ApiResponse[None](message="Password updated. Please sign in.")


@router.get("/me", response_model=ApiResponse[MeResponse])
async def me_endpoint(current_user: CurrentUser) -> ApiResponse[MeResponse]:
    return ApiResponse[MeResponse](
        data=MeResponse(
            id=str(current_user.id),
            email=current_user.email,
            plan=current_user.plan.value
            if hasattr(current_user.plan, "value")
            else current_user.plan,
            is_admin=current_user.is_admin,
            is_super_admin=current_user.is_super_admin,
            email_verified=current_user.email_verified,
            created_at=current_user.created_at.isoformat(),
        ),
    )
