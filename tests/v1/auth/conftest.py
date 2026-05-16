import asyncio
import logging.config
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://anvila_test:anvila_test_pass@localhost:5432/anvila_backend_test",
)
os.environ.setdefault("JWT_SECRET", "ci-test-secret-key-minimum-32-characters-long")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402

TEST_DB_URL = os.environ["DATABASE_URL"]


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
    await engine.dispose()


@pytest.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)
