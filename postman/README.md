# Postman — Anvila Auth API

Comprehensive request suite covering the email/password flow, password reset, session management, Google OAuth, GitHub OAuth, and the OAuth link-confirmation flow.

## Files

- `anvila-auth.postman_collection.json` — the collection. Import once.
- `local.postman_environment.json` — variables for `http://localhost:8000`. Use during local development.
- `staging.postman_environment.json` — variables for `https://api.staging.anvila.hng14.com`. Use against the staging deployment.

## Running the backend locally

The Postman collection assumes a backend reachable at `http://localhost:8000` (configurable via `{{base_url}}`). This section walks through bringing one up from a fresh clone.

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) installed (`pip install uv` or via the installer script)
- Docker Desktop (for the Postgres container) **OR** a local Postgres 14+ instance you control

### 1. Install dependencies

From the repo root:

```bash
uv sync --all-groups
```

This creates `.venv/` and installs runtime + dev + test dependencies.

### 2. Start Postgres

**Option A — Docker (recommended):**

```bash
docker run -d \
  --name anvila_backend_dev_db \
  -e POSTGRES_USER=anvila \
  -e POSTGRES_PASSWORD=anvila_dev_pass \
  -e POSTGRES_DB=anvila_backend \
  -p 5432:5432 \
  postgres:16
```

Wait ~3 seconds for the container to accept connections (`docker logs anvila_backend_dev_db | tail -5` should show `database system is ready to accept connections`).

**Option B — Local Postgres:**

```sql
CREATE USER anvila WITH PASSWORD 'anvila_dev_pass';
CREATE DATABASE anvila_backend OWNER anvila;
GRANT ALL PRIVILEGES ON DATABASE anvila_backend TO anvila;
```

Then make sure your Postgres is listening on `localhost:5432`.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in at minimum:

```bash
cp .env.example .env
```

Set these in `.env`:

```env
DATABASE_URL=postgresql+asyncpg://anvila:anvila_dev_pass@localhost:5432/anvila_backend
JWT_SECRET=local-dev-secret-key-minimum-32-characters
GITHUB_CLIENT_ID=<your local GitHub OAuth app client id>
GITHUB_CLIENT_SECRET=<your local GitHub OAuth app client secret>
GITHUB_REDIRECT_URI=http://localhost:8000/api/v1/auth/github/callback
GITHUB_OAUTH_ENABLED=true
GOOGLE_CLIENT_ID=<placeholder; real value only needed for Google OAuth testing>
GOOGLE_CLIENT_SECRET=<placeholder>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
FRONTEND_URL=http://localhost:3000
COOKIE_SECURE=false
```

For local-only verification of GitHub OAuth, you'll need to create a GitHub OAuth app at <https://github.com/settings/developers> with the **Authorization callback URL** set to `http://localhost:8000/api/v1/auth/github/callback`. The `Client ID` and the generated `Client Secret` go into the env file.

### 4. Run migrations

With `.env` in place:

```bash
uv run alembic upgrade head
```

You should see four migrations apply in order:

```
9e38c7d41d38 → a1b2c3d4e5f6 → b2c3d4e5f6a7 → e1f2a3b4c5d6
```

If the DB connection fails here, the most common causes are: container not actually ready (`docker ps` to confirm), wrong port in `DATABASE_URL` (Docker default is 5432, but if you have another Postgres on 5432 already use a different host port like `-p 5433:5432` and update `DATABASE_URL` accordingly), or `anvila` user does not own the database.

### 5. Start the server

```bash
uv run uvicorn app.main:app --reload --port 8000
```

You should see `Application startup complete.` Visit:

- <http://localhost:8000/docs> — Swagger UI
- <http://localhost:8000/api/v1/health> — health check

If the GitHub OAuth routes don't appear in the OpenAPI schema, double-check `GITHUB_OAUTH_ENABLED=true` in `.env` and restart the server. The flag is read at startup, not per-request.

### 6. Verify DB connectivity from Postman

In Postman, with the **Local** environment selected, run **1. Health → GET /health**. Expect `200 OK`. Then run **2. Email/Password Auth → POST /auth/register**. Expect `201 Created` and a user row in the `users` table:

```bash
docker exec anvila_backend_dev_db psql -U anvila -d anvila_backend -c "SELECT email, email_verified FROM users;"
```

If the register call returns `500`, the most common cause is a DB connection that the app can't reach (check the uvicorn log for `asyncpg.exceptions.InvalidPasswordError` or similar).

## Postman setup

1. Import the collection (`File → Import` in Postman).
2. Import both environments.
3. Pick the appropriate environment from the dropdown before running.
4. Run the **Email/Password Auth → POST /auth/login** request first to populate `{{access_token}}` and `{{refresh_token}}` (the test script captures both).

## Sequencing

The auth API has temporal dependencies. Run in this order for a full sweep:

1. **Health** → confirms the server is reachable.
2. **Register** → creates the user, returns `email_verified: false`.
3. **Verify email** → requires `{{verification_token}}`, which you copy from the dev logs (local) or the test inbox (staging).
4. **Login** → confirms credentials, populates `{{access_token}}` and `{{refresh_token}}`.
5. **GET /auth/me** → smoke-tests the bearer flow.
6. **Refresh** → exchanges `{{refresh_token}}` for a new access token; re-populates `{{access_token}}`.
7. **Logout** → revokes the refresh token.

The OAuth folders require manual coordination — see below.

## OAuth flows are partially manual

Postman cannot drive a browser-based OAuth consent screen. The non-manual requests still verify the parts Postman can:

- **GitHub OAuth start** (`GET /auth/github`) — confirms the 307 redirect, the `client_secret`-free URL, the state cookie, and the scope value (`read:user user:email`).
- **GitHub OAuth callback (state mismatch)** — negative test for AUTH-REQ-033. Asserts 400 and confirms the token exchange is never attempted.
- **GitHub OAuth callback (provider error)** — confirms safe 400 handling for `error=access_denied`.

For the full happy-path callback, run the start request, open the `Location` header in a browser, complete consent, copy the `code` from the resulting callback URL and the `oauth_state` cookie value into the environment variables, then fire the **manual full flow** request.

## OAuth link-confirmation (TC-036 D path)

When a GitHub OAuth callback resolves to a verified email that already belongs to a local user, the response contains `link_confirmation_required: true` instead of a token. The backend emails a one-shot confirmation link.

To exercise locally:

1. Run the GitHub callback flow with an email that matches an existing local account.
2. Check the dev logs for the link-confirmation event. The raw token is logged only in development; in staging/production it is hashed.
3. Set `{{link_token}}` to the raw token.
4. Run **OAuth Link Confirmation → GET /auth/oauth/confirm-link (valid)**.

The token has a 30-minute TTL and is one-shot. Replaying it returns 400 with the anti-enumeration message.

## Coverage

| Requirement | Postman request | Status |
|---|---|---|
| AUTH-REQ-010 (button initiates consent) | GitHub OAuth → start | Automated |
| AUTH-REQ-032 (state random, 10-min TTL) | GitHub OAuth → start (tests check state present) | Automated; TTL verified via code review |
| AUTH-REQ-033 (state mismatch returns 400) | GitHub OAuth → callback (state mismatch) | Automated |
| AUTH-REQ-034 (`client_secret` never in browser) | GitHub OAuth → start (test asserts `client_secret` absent) | Automated |
| AUTH-REQ-035 (same-email collision) | GitHub OAuth → callback (manual full flow) | Manual; observe `link_confirmation_required` |
| TC-037 (new OAuth user auto-verified) | GitHub OAuth → callback (manual full flow) | Manual; observe immediate access token |
| Feature flag off | GitHub OAuth → start | Manual; run against deployment with `GITHUB_OAUTH_ENABLED=false` |

## Newman

To run the automated subset in CI:

```bash
npm install -g newman
newman run postman/anvila-auth.postman_collection.json \
  -e postman/local.postman_environment.json \
  --folder "1. Health" \
  --folder "2. Email/Password Auth" \
  --folder "5. Session Management" \
  --folder "7. GitHub OAuth"
```

Folders that contain manual-only requests (Google/GitHub full callback, link confirmation) are excluded from the Newman sweep because they require human interaction.

## Maintenance

Keep the collection in sync with the API:

- When a new endpoint is added, add a corresponding request with at minimum a status-code assertion.
- When a response envelope changes, update the test scripts (they currently assert `body.data.*`).
- When a new env var is required (e.g. an additional OAuth provider), add it to both environment files with empty/sensitive markers.
