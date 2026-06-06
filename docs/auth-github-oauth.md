# GitHub OAuth — API Contract

## Overview

This document describes the backend GitHub OAuth flow used by Anvila for sign-in and sign-up. The implementation authenticates users via GitHub's authorization code grant, resolves a verified email from GitHub, and either logs the user in directly or sends an email-based confirmation link before linking a GitHub identity to a pre-existing local account.

The flow is read-only with respect to GitHub. It requests `read:user user:email` scopes only; it does not publish on the user's behalf, create repositories, or store the GitHub access token. The GitHub user `id` is stored as a stable provider key (`users.github_subject`); the `login` is stored as a non-unique informational field (`users.github_username`).

## Endpoints

### `GET /api/v1/auth/github`

Start the GitHub OAuth flow. Mints a signed `oauth_state` JWT, sets it as an HTTP-only cookie, and 307-redirects the browser to GitHub's authorization page.

- **Auth required**: none.
- **Query parameters**: none.
- **Required cookies**: none (the response sets `oauth_state`).
- **Success response** (`307 Temporary Redirect`):
  - `Location: https://github.com/login/oauth/authorize?client_id=...&redirect_uri=...&scope=read:user+user:email&state=...&response_type=code&allow_signup=true`
  - `Set-Cookie: oauth_state=<jwt>; HttpOnly; SameSite=Lax`
- **Side effects**: none on the database.

This route only exists when `GITHUB_OAUTH_ENABLED=true`.

### `GET /api/v1/auth/github/callback`

The redirect target GitHub calls after the user authorizes. Validates the state cookie against the query, decodes the state JWT, exchanges the code for a GitHub access token, fetches profile and verified emails, then dispatches one of three outcomes.

- **Auth required**: none (the request originates from a top-level redirect from GitHub).
- **Query parameters**:
  - `code: string` (required on success)
  - `state: string` (required on success)
  - `error: string` (set by GitHub on user cancellation, e.g. `access_denied`)
  - `error_description: string` (optional human-readable description from GitHub)
- **Required cookies**: `oauth_state` (set by the start route). Must equal the `state` query parameter.
- **Success response — completed login** (`200 OK`):
  ```json
  {
    "success": true,
    "message": "Login successful.",
    "data": {
      "user": { "id": "...", "email": "...", "...": "..." },
      "tokens": {
        "access_token": "...",
        "refresh_token": "...",
        "token_type": "bearer"
      }
    },
    "meta": null
  }
  ```
  Also sets `refresh_token` cookie and clears `oauth_state`.
- **Success response — link confirmation required** (`200 OK`):
  ```json
  {
    "success": true,
    "message": "We've sent a confirmation link to your email. Click the link to finish connecting your GitHub account.",
    "data": {
      "link_confirmation_required": true,
      "email_destination_hint": "j***@e***.com"
    },
    "meta": null
  }
  ```
  No tokens are issued. No refresh cookie is set. `oauth_state` is cleared. A confirmation email is scheduled via `BackgroundTasks`.
- **Error response shape**: `{"detail": "..."}` with the appropriate status code. See error matrix below.
- **Side effects**:
  - Creates a `users` row on first-time sign-in (`provider=GITHUB`, `email_verified=true`).
  - Updates an existing user's `github_subject` and profile fields on returning sign-in.
  - Revokes all active refresh tokens for the user and writes a new `refresh_tokens` row on the login-completed path.
  - Writes an `oauth_link_tokens` row on the link-confirmation path.
  - Schedules an outbound email on the link-confirmation path.

### `GET /api/v1/auth/oauth/confirm-link`

Token-gated. Consumes a one-shot link-confirmation token, links the pending GitHub identity to the existing user, rotates refresh tokens, and logs the user in.

- **Auth required**: none (the token itself authorizes the call).
- **Query parameters**:
  - `token: string` (required) — the raw token mailed to the user.
- **Required cookies**: none.
- **Success response** (`200 OK`):
  ```json
  {
    "success": true,
    "message": "GitHub account linked. Login successful.",
    "data": {
      "user": { "id": "...", "email": "...", "...": "..." },
      "tokens": { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
    },
    "meta": null
  }
  ```
  Sets `refresh_token` cookie.
- **Error response shape**: `{"detail": "..."}` with the appropriate status code.
- **Side effects**:
  - Marks the `oauth_link_tokens` row as consumed.
  - Sets `users.github_subject` on the target row.
  - Marks the user as email-verified.
  - Revokes all active refresh tokens for the user and writes a new `refresh_tokens` row.

## Environment variables

| Name | Description | Required | Default | Sensitive |
|------|-------------|----------|---------|-----------|
| `GITHUB_CLIENT_ID` | OAuth client ID from the GitHub OAuth app. | yes | — | no |
| `GITHUB_CLIENT_SECRET` | OAuth client secret from the GitHub OAuth app. | yes | — | yes |
| `GITHUB_REDIRECT_URI` | Public URL of `/api/v1/auth/github/callback` for the deployed environment. | yes | — | no |
| `GITHUB_AUTH_URL` | GitHub's authorize endpoint. | no | `https://github.com/login/oauth/authorize` | no |
| `GITHUB_TOKEN_URL` | GitHub's token-exchange endpoint. | no | `https://github.com/login/oauth/access_token` | no |
| `GITHUB_USERINFO_URL` | GitHub's authenticated user endpoint. | no | `https://api.github.com/user` | no |
| `GITHUB_EMAILS_URL` | GitHub's authenticated user-emails endpoint. | no | `https://api.github.com/user/emails` | no |
| `GITHUB_SCOPES` | Space-separated OAuth scopes requested. | no | `read:user user:email` | no |
| `GITHUB_OAUTH_ENABLED` | Feature flag for staged rollout. When false, the three GitHub OAuth routes are not registered at all. | no | `false` | no |
| `OAUTH_LINK_TOKEN_EXPIRE_MINUTES` | TTL for link-confirmation tokens. | no | `30` | no |
| `FRONTEND_URL` | Used to build the link-confirmation URL embedded in the outbound email. | yes (already required) | `http://localhost:3000` | no |

Secret values must never be committed. They are loaded from environment or `.env` at process start.

## Error matrix

| Status | Detail | Cause | Recovery |
|--------|--------|-------|----------|
| 400 | `GitHub OAuth failed` (or provider `error_description`) | User cancelled at the GitHub consent screen, or GitHub returned `error=access_denied`. | Re-initiate from `/api/v1/auth/github`. |
| 400 | `Missing OAuth parameters` | Callback called without `code`, `state`, or the `oauth_state` cookie. | Re-initiate the flow from the start route. |
| 400 | `Invalid OAuth state` | The `state` query and `oauth_state` cookie do not match. Possible CSRF or stale tab. | Re-initiate the flow. |
| 401 | `Token expired` / `Invalid token` | State JWT failed signature, expiry, or purpose validation. | Re-initiate the flow. |
| 400 | `GitHub account has no verified email` | None of the addresses returned by `/user/emails` are verified. | User must verify an email on GitHub, then retry. |
| 403 | `Account is disabled` | The local user matched by `github_subject` or `email` is inactive. | Contact support. |
| 502 | `GitHub token exchange failed` | Token endpoint returned 4xx, returned 200 without `access_token`, or the network request errored. | Retry the flow; if persistent, suspect provider outage. |
| 502 | `GitHub profile fetch failed` | `/user` returned non-2xx or network error. | Retry. |
| 502 | `GitHub email fetch failed` | `/user/emails` returned non-2xx or network error. | Retry. |
| 502 | `GitHub profile missing id` | Profile response did not contain `id`. | Retry; if persistent, suspect provider regression. |
| 500 | `Failed to resolve user after concurrent OAuth registration` | Race-condition rescue could not locate the surviving row. | Retry. |
| 400 | `Invalid or expired link token` | Confirm-link token is unknown, already consumed, or expired. The response shape is identical for all three to resist enumeration. | Re-initiate the OAuth flow to receive a fresh confirmation link. |
| 403 | `Account is disabled` | Confirm-link token references a user whose `is_active` flag is now false. | Contact support. |

No provider response bodies are echoed in error details. Tokens, codes, and client secrets never appear in any response.

## Feature flag

`GITHUB_OAUTH_ENABLED` gates conditional registration of the three GitHub routes at FastAPI app construction. When the flag is false, the routes are absent from the OpenAPI schema and return 404. When the flag is true, the routes are registered.

Rollout protocol:

1. Deploy the build with the flag false. The three routes are not exposed.
2. Flip the flag to true in the staging environment. QA exercises the full flow.
3. Once signed off, flip the flag to true in production. No code change required.

Rollback is a single environment-variable flip and a process restart. There is no in-flight session to migrate; the change only affects whether new flows can start.

## Frontend expectations

The frontend's GitHub button should set `window.location` to `${API_BASE}/api/v1/auth/github`. The browser follows the 307 redirect to GitHub. GitHub redirects back to `${API_BASE}/api/v1/auth/github/callback` after user consent.

The callback response is a JSON envelope. The frontend must inspect `data` to distinguish the two success branches:

- If `data.tokens` is present, the user is logged in. Store `access_token` per the existing session strategy. The `refresh_token` cookie has already been set by the backend.
- If `data.link_confirmation_required === true`, the user must check their email. Render the `email_destination_hint` (already masked, safe to display) and instruct the user to click the link in the email to finish connecting their GitHub account. Do not retry the OAuth flow automatically.

The link-confirmation email contains a URL of the form `${FRONTEND_URL}/api/v1/auth/oauth/confirm-link?token=...`. The frontend (or a proxy) is responsible for routing that path to the backend's confirm endpoint. On success the response is the same `LoginData` envelope shape as a normal login; on failure the response is `{"detail": "Invalid or expired link token"}` with HTTP 400, and the frontend should ask the user to restart the OAuth flow.
