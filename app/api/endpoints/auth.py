from fastapi import APIRouter, Cookie, Query, HTTPException, Request, Response, status

from app.core.security import create_oauth_state_token, decode_token
from app.services.auth import (
    OAUTH_STATE_COOKIE,
    build_google_auth_url,
    clear_oauth_state_cookie,
    exchange_google_code,
    fetch_google_userinfo,
    login_or_register_google_user,
    set_oauth_state_cookie,
    set_refresh_token_cookie,
)

from app.schemas.auth import TokenResponse
from app.api.deps import DBSession

router = APIRouter()

@router.get("/google", summary="Start Google OAuth flow")
async def google_start(response: Response) -> Response:
    state = create_oauth_state_token()
    
    set_oauth_state_cookie(response, state)

    response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
    response.headers["Location"] = build_google_auth_url(state)

    return response


@router.get(
    "/google/callback",
    response_model=TokenResponse,
    response_model_exclude_none=True,
    summary="Handle Google OAuth callback",
)
async def google_callback(
    request: Request,
    response: Response,
    db: DBSession,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
) -> TokenResponse:
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

        payload = decode_token(state)

        if payload.get("purpose") != "oauth_state":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state",
            )

        token_payload = await exchange_google_code(code)

        google_access_token = token_payload.get("access_token")

        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google token response missing access token",
            )

        profile = await fetch_google_userinfo(google_access_token)

        access_token, raw_refresh, _ = await login_or_register_google_user(
            db=db,
            profile=profile,
            request=request,
        )

        set_refresh_token_cookie(response, raw_refresh)
        clear_oauth_state_cookie(response)

        return TokenResponse(access_token=access_token)

    except HTTPException:
        clear_oauth_state_cookie(response)
        raise