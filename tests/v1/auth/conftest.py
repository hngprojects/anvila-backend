import asyncio
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://anvila_test:anvila_test_pass@localhost:5432/anvila_backend_test",
)
os.environ.setdefault("JWT_SECRET", "ci-test-secret-key-minimum-32-characters-long")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8000/api/v1/auth/google/callback",
)
os.environ.setdefault("GITHUB_CLIENT_ID", "test-github-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-github-client-secret")
os.environ.setdefault(
    "GITHUB_REDIRECT_URI",
    "http://localhost:8000/api/v1/auth/github/callback",
)
os.environ.setdefault("GITHUB_OAUTH_ENABLED", "true")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402

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
