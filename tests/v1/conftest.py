import asyncio
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://anvila_test:anvila_test_pass@localhost:5432/anvila_backend_test",
)
os.environ.setdefault("JWT_SECRET", "ci-test-secret-key-minimum-32-characters-long")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-github-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-github-client-secret")
os.environ.setdefault("GITHUB_REDIRECT_URI", "http://localhost:8000/api/v1/auth/github/callback")
os.environ.setdefault("GITHUB_OAUTH_ENABLED", "true")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.models  # noqa: E402, F401 — registers all ORM tables on Base.metadata
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import UserPlan, UserProvider  # noqa: E402
from app.models.user import User  # noqa: E402

TEST_DB_URL = os.environ["DATABASE_URL"]

if "test" not in TEST_DB_URL.lower():
    raise RuntimeError(
        f"DATABASE_URL does not look like a test database: {TEST_DB_URL!r}. "
        "Refusing to run destructive test operations against a non-test database."
    )


def _make_engine():
    return create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)


@pytest.fixture(scope="session", autouse=True)
def create_test_tables():
    async def _setup():
        engine = _make_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    async def _teardown():
        engine = _make_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = _make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    table_names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_session, None)


# ── Auth helpers ──────────────────────────────────────────────────────────────


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ── User factories ────────────────────────────────────────────────────────────


@pytest.fixture()
async def free_user(db_session: AsyncSession) -> User:
    user = User(
        email="free@test.com",
        password_hash=hash_password("Password123"),
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
async def paid_user(db_session: AsyncSession) -> User:
    user = User(
        email="paid@test.com",
        password_hash=hash_password("Password123"),
        provider=UserProvider.EMAIL,
        plan=UserPlan.PAID,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin@test.com",
        password_hash=hash_password("Password123"),
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
