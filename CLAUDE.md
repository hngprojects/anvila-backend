# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Install dependencies (Python 3.13, managed by uv):**
```sh
uv sync
uv sync --group dev  # include dev dependencies
```

**Run the server:**
```sh
# New Anvila app (app/ directory) — the active target
uvicorn app.main:app --reload --port 8000

# Legacy app entry point (still referenced by tests)
python main.py  # starts on port 7001 with hot reload
```

**Lint:**
```sh
ruff check .
ruff format .
```

**Run all tests:**
```sh
pytest
pytest -v               # verbose
pytest --cov=api        # with coverage
```

**Run a specific test file or function:**
```sh
pytest tests/v1/auth/test_request_pwd_reset.py
pytest tests/v1/auth/test_request_pwd_reset.py::test_reset_password
```

**Database migrations (targets legacy schema, reads `DB_URL` from `.env`):**
```sh
alembic upgrade head
alembic revision --autogenerate -m "your migration message"
```

## Architecture

### New app (`app/`) — Anvila target architecture

Entry point: `app/main.py` → `app/api/router.py` under prefix `/api/v1`.

- **`app/core/config.py`** — Pydantic `Settings` via `pydantic-settings`. Key env vars: `DATABASE_URL` (asyncpg DSN), `JWT_SECRET`, OAuth credentials.
- **`app/db/session.py`** — Async SQLAlchemy engine. `get_session()` is the FastAPI dependency.
- **`app/api/deps.py`** — `DBSession = Annotated[AsyncSession, Depends(get_session)]` — use this type in route signatures.
- **`app/api/router.py`** — Central router; register new endpoint routers here.
- **`app/api/endpoints/`** — Individual route files. `health.py` is the reference example.
- **`app/models/`**, **`app/schemas/`**, **`app/services/`** — empty; fill these as features are added.

All DB calls in this layer are `async/await`.

### Legacy layer (`api/`) — source deleted, bytecode only

The `api/` source files were removed during repo cleanup. Only compiled `.pyc` files survive in `api/**/__pycache__/`. **Do not try to read or edit legacy source files — they don't exist.**

Two source files remain because they were added on the current feature branch:
- [api/v1/models/reset_password_token.py](api/v1/models/reset_password_token.py)
- [api/v1/services/request_pwd.py](api/v1/services/request_pwd.py)

The tests and the legacy `main.py` still run against the bytecode. `alembic/env.py` also imports from the legacy `api/` models via bytecode.

## Testing notes

Tests in `tests/` exercise the legacy layer. `conftest.py` creates a real PostgreSQL session (from `DB_URL` in `.env`) and wraps each test in a transaction rolled back afterward — no cleanup needed. Do not mock the database.

New `app/`-layer tests use `pytest-asyncio` (`asyncio_mode = "auto"` is set in `pyproject.toml`).

`ENABLE_INSECURE_TEST_ENDPOINTS` must remain `false`.

## Pre-commit hooks

`.husky/pre-commit` auto-fixes lines over 200 characters and blocks commits containing obfuscation patterns (`eval(`, `String.fromCharCode`, etc.) and Python config injection patterns. Runs automatically via `pre-commit`.
