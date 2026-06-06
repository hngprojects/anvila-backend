import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DBSession
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token_for_user,
    create_oauth_state_token,
    decode_token,
)
from app.email.sender import (
    send_oauth_link_email,
    send_password_reset_email,
    send_verification_email,
)
from app.models.refresh_token import RefreshToken
from app.schemas.auth import (
    ForgotPasswordRequest,
    LinkConfirmationData,
    LoginData,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    OTTExchangeRequest,
    RefreshData,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.schemas.shared import ApiResponse
from app.services import auth as auth_service
from app.services.auth import (
    OAUTH_STATE_COOKIE,
    clear_oauth_state_cookie,
    get_user_by_id,
    revoke_all_active_refresh_tokens,
    set_oauth_state_cookie,
    set_refresh_token_cookie,
)
from app.services.github_oauth import (
    GITHUB_LINK_CONFIRMATION_PATH,
    GitHubOAuthIntent,
    LoginCompleted,
    apply_github_link,
    build_github_auth_url,
    create_github_connect_state,
    create_github_login_state,
    decode_github_state,
    process_github_callback,
)
from app.services.google_oauth import (
    build_google_auth_url,
    exchange_google_code,
    fetch_google_userinfo,
    login_or_register_google_user,
)
from app.services.oauth_link import consume_link_token
from app.services.ott_store import consume_ott, redirect_with_ott

router = APIRouter(prefix="/auth", tags=["auth"])

_logger = logging.getLogger(__name__)


@router.post(
    "/register",
    response_model=ApiResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/hour")
async def register(
    request: Request, body: RegisterRequest, db: DBSession, bg_task: BackgroundTasks
) -> ApiResponse[UserResponse]:
    try:
        user, verification_url = await auth_service.register_user(
            db,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from e

    await db.refresh(user)
    bg_task.add_task(send_verification_email, user.email, verification_url)

    return ApiResponse[UserResponse](
        message="Registration successful. Please check your email to verify your account.",
        data=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=ApiResponse[LoginData])
@limiter.limit("10/minute")
async def login(body: LoginRequest, request: Request, db: DBSession) -> ApiResponse[LoginData]:
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    result = await auth_service.login_user(
        db,
        email=body.email,
        password=body.password,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    return ApiResponse[LoginData](
        message="Login successful.",
        data=LoginData(
            user=UserResponse.model_validate(result["user"]),
            tokens=TokenResponse(
                access_token=result["access_token"],
                refresh_token=result["refresh_token"],
            ),
        ),
    )


@router.post("/verify-email", response_model=ApiResponse[UserResponse])
@limiter.limit("10/hour")
async def verify_email(
    request: Request, body: VerifyEmailRequest, db: DBSession
) -> ApiResponse[UserResponse]:
    user = await auth_service.verify_email(db, body.token)
    await db.commit()
    await db.refresh(user)

    return ApiResponse[UserResponse](
        message="Email verified successfully.",
        data=UserResponse.model_validate(user),
    )


@router.post(
    "/resend-verification",
    response_model=ApiResponse[None],
    status_code=status.HTTP_202_ACCEPTED,  # accept
)
@limiter.limit("3/hour")
async def resend_verification(
    request: Request, body: ResendVerificationRequest, db: DBSession, bg_task: BackgroundTasks
) -> ApiResponse[None]:
    verification_url = await auth_service.resend_verification_email(db, body.email)

    if verification_url:
        bg_task.add_task(send_verification_email, body.email, verification_url)

    # Intentionally vague — never reveal whether the address exists
    return ApiResponse[None](
        message=(
            "If this email is registered and unverified, a new verification link has been sent."
        ),
    )


@router.post("/refresh", response_model=ApiResponse[RefreshData])
@limiter.limit("30/minute")
async def refresh_token_endpoint(
    request: Request, body: RefreshRequest, db: DBSession
) -> ApiResponse[RefreshData]:
    access_token = await auth_service.refresh_access_token(db, body.refresh_token)

    return ApiResponse[RefreshData](
        message="Token refreshed.",
        data=RefreshData(access_token=access_token),
    )


@router.post("/logout", response_model=ApiResponse[None], status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def logout_endpoint(
    request: Request, body: LogoutRequest, db: DBSession
) -> ApiResponse[None]:
    await auth_service.logout_user(db, body.refresh_token)
    await db.commit()

    return ApiResponse[None](message="Logged out successfully.")


@router.post("/forgot-password", response_model=ApiResponse[None])
@limiter.limit("3/hour")
async def forgot_password(
    request: Request, body: ForgotPasswordRequest, db: DBSession, bg_task: BackgroundTasks
) -> ApiResponse[None]:
    raw_token = await auth_service.create_password_reset_token(db, body.email)

    if raw_token:
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
        bg_task.add_task(send_password_reset_email, body.email, reset_url)

    # Intentionally vague — never reveal whether the email exists or has a password account
    return ApiResponse[None](
        message="If this email exists and has a password account, a reset link has been sent.",
    )


@router.post("/reset-password", response_model=ApiResponse[None])
@limiter.limit("5/hour")
async def reset_password_endpoint(
    request: Request, body: ResetPasswordRequest, db: DBSession
) -> ApiResponse[None]:
    success = await auth_service.reset_password(db, body.token, body.new_password)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    return ApiResponse[None](message="Password updated. Please sign in.")


@router.get("/me", response_model=ApiResponse[MeResponse])
@limiter.limit("60/minute")
async def me_endpoint(request: Request, current_user: CurrentUser) -> ApiResponse[MeResponse]:
    return ApiResponse[MeResponse](
        data=MeResponse(
            id=str(current_user.id),
            email=current_user.email,
            plan=current_user.plan.value
            if hasattr(current_user.plan, "value")
            else current_user.plan,
            display_name=current_user.display_name,
            is_admin=current_user.is_admin,
            is_super_admin=current_user.is_super_admin,
            email_verified=current_user.email_verified,
            created_at=current_user.created_at.isoformat(),
            github_subject=current_user.github_subject,
            github_username=current_user.github_username,
            github_connected=current_user.github_connected,
        ),
    )


# OAuth
# ==============
@router.get("/google", summary="Start Google OAuth flow")
async def google_start(response: Response) -> Response:
    """Redirect the user to Google's consent screen."""
    state = create_oauth_state_token()
    set_oauth_state_cookie(response, state)
    response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
    response.headers["Location"] = build_google_auth_url(state)
    return response


@router.get("/google/callback", summary="Handle Google OAuth callback")
async def google_callback(
    request: Request,
    response: Response,
    db: DBSession,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
) -> RedirectResponse:
    """Validate state, exchange code for tokens, issue app tokens, clear cookies."""
    try:
        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_description or "Google OAuth failed",
            )

        if not code or not state or not state_cookie:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing OAuth parameters",
            )

        if state != state_cookie:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state",
            )

        decode_token(state, expected_purpose="oauth_state")

        token_payload = await exchange_google_code(code)
        google_access_token = token_payload.get("access_token")

        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google token response missing access token",
            )

        profile = await fetch_google_userinfo(google_access_token)
        access_token, raw_refresh, user = await login_or_register_google_user(
            db=db,
            profile=profile,
            request=request,
        )

        set_refresh_token_cookie(response, raw_refresh)
        clear_oauth_state_cookie(response)

        return await redirect_with_ott(access_token, raw_refresh, UserResponse.model_validate(user))

    except HTTPException as exc:
        error_response = JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "message": exc.detail},
        )
        clear_oauth_state_cookie(error_response)
        return error_response  # pyright: ignore[reportReturnType]


# GitHub OAuth
# ==============
def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not local or not domain:
        return "***"
    domain_name, _, tld = domain.rpartition(".")
    if not domain_name:
        # No dot in domain; mask everything after first char.
        return f"{local[0]}***@{domain[0]}***"
    masked_local = f"{local[0]}{'*' * 3}"
    masked_domain = f"{domain_name[0]}{'*' * 3}"
    return f"{masked_local}@{masked_domain}.{tld}"


_github_router = APIRouter(tags=["auth"])


@_github_router.get("/github", summary="Start GitHub OAuth flow")
async def github_start(response: Response) -> Response:
    state = create_github_login_state()
    set_oauth_state_cookie(response, state)
    response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
    response.headers["Location"] = build_github_auth_url(state)
    return response


@_github_router.get("/github/connect", summary="Connect GitHub to existing account")
async def github_connect_start(
    response: Response,
    current_user: CurrentUser,
) -> Response:
    state = create_github_connect_state(str(current_user.id))
    response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
    response.headers["Location"] = build_github_auth_url(state)
    return response


@_github_router.get(
    "/github/callback",
    summary="Handle GitHub OAuth callback",
    response_model=None,
)
async def github_callback(
    request: Request,
    response: Response,
    db: DBSession,
    bg_task: BackgroundTasks,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
) -> RedirectResponse | ApiResponse[LinkConfirmationData]:
    try:
        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_description or "GitHub OAuth failed",
            )
        if not code or not state or not state_cookie:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing OAuth parameters",
            )
        # Cookie-equality before JWT decode keeps the CSRF check independent of signing.
        if state != state_cookie:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state",
            )
        intent, connect_user_id = decode_github_state(state)

        if intent == GitHubOAuthIntent.CONNECT:
            await process_github_callback(
                db, code=code, request=request, connect_for_user_id=connect_user_id
            )
            await db.commit()
            # FE already has a valid session — just redirect back, it calls /me to refresh state
            redirect = RedirectResponse(
                f"{settings.FRONTEND_URL}/connections/github?github=connected",
                status_code=302,
            )
            clear_oauth_state_cookie(redirect)
            return redirect

        outcome = await process_github_callback(db, code=code, request=request)

        if isinstance(outcome, LoginCompleted):
            await db.commit()
            await db.refresh(outcome.user)
            redirect = await redirect_with_ott(
                outcome.access_token,
                outcome.raw_refresh,
                UserResponse.model_validate(outcome.user),
            )
            set_refresh_token_cookie(redirect, outcome.raw_refresh)
            return redirect

        # LinkConfirmationRequired branch — persist the link-token row, send email,
        # but never log the user in or set a refresh cookie.
        await db.commit()
        clear_oauth_state_cookie(response)
        link_url = (
            f"{settings.FRONTEND_URL}{GITHUB_LINK_CONFIRMATION_PATH}?token={outcome.link_token}"  # type: ignore
        )
        bg_task.add_task(send_oauth_link_email, outcome.email, link_url)  # type: ignore
        return ApiResponse[LinkConfirmationData](
            message=(
                "We've sent a confirmation link to your email. "
                "Click the link to finish connecting your GitHub account."
            ),
            data=LinkConfirmationData(
                link_confirmation_required=True,
                email_destination_hint=_mask_email(outcome.email),  # type: ignore
            ),
        )

    except HTTPException:
        await db.rollback()
        clear_oauth_state_cookie(response)
        raise
    except Exception:
        await db.rollback()
        clear_oauth_state_cookie(response)
        _logger.exception("event=auth.oauth.github.callback.error outcome=unhandled")
        raise


@_github_router.get(
    "/oauth/confirm-link",
    response_model=ApiResponse[LoginData],
    summary="Confirm OAuth identity link",
)
async def confirm_link(
    request: Request,
    response: Response,
    db: DBSession,
    token: str = Query(...),
) -> ApiResponse[LoginData]:
    try:
        row = await consume_link_token(db, token)

        user = await get_user_by_id(db, row.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired link token",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )

        apply_github_link(
            user,
            github_subject=row.provider_subject,
            github_username=None,
        )

        await revoke_all_active_refresh_tokens(db, user.id)

        access_token = create_access_token_for_user(user)
        raw_refresh = secrets.token_urlsafe(32)
        refresh_record = RefreshToken(
            token_hash=hashlib.sha256(raw_refresh.encode()).hexdigest(),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
        db.add(refresh_record)
        await db.commit()
        await db.refresh(user)

        set_refresh_token_cookie(response, raw_refresh)

        _logger.info(
            "event=auth.oauth.github.link_confirmed outcome=success user_id=%s email_hash=%s",
            user.id,
            hashlib.sha256(user.email.lower().encode()).hexdigest()[:16],
        )

        return ApiResponse[LoginData](
            message="GitHub account linked. Login successful.",
            data=LoginData(
                user=UserResponse.model_validate(user),
                tokens=TokenResponse(
                    access_token=access_token,
                    refresh_token=raw_refresh,
                ),
            ),
        )
    except HTTPException as exc:
        await db.rollback()
        _logger.warning(
            "event=auth.oauth.github.link_failed outcome=error error_class=%s",
            exc.__class__.__name__,
        )
        raise
    except Exception:
        await db.rollback()
        _logger.exception("event=auth.oauth.github.link_failed outcome=unhandled")
        raise


@router.post("/token/exchange", response_model=ApiResponse[LoginData])
async def exchange_ott(
    body: OTTExchangeRequest,
    response: Response,
):
    """Exchange a one-time token for real access/refresh tokens."""
    result = await consume_ott(body.ott)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired one-time token.",
        )

    access_token = result.access_token
    raw_refresh = result.raw_refresh
    user = result.user
    set_refresh_token_cookie(response, raw_refresh)
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


if settings.GITHUB_OAUTH_ENABLED:
    router.include_router(_github_router)
