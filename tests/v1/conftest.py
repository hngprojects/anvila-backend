import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import create_access_token_for_user
from app.db.session import get_session
from app.main import app
from app.models.base import Base
from app.models.enums import UserPlan, UserProvider
from app.models.user import User

# Env setdefaults live in tests/conftest.py — must run before app.core.config
# is imported by any test module.

TEST_DB_URL = os.environ["DATABASE_URL"]
_db_name = (make_url(TEST_DB_URL).database or "").lower()
if not (_db_name.endswith("_test") or _db_name.startswith("test_")):
    raise RuntimeError(
        f"DATABASE_URL is not an approved test database name: {_db_name!r}. "
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


@pytest.fixture()
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"test-user-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
async def free_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"free-user-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
async def paid_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"paid-user-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.PAID,
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin-user-{uuid.uuid4().hex[:8]}@test.local",
        provider=UserProvider.EMAIL,
        plan=UserPlan.FREE,
        email_verified=True,
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token_for_user(test_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def auth_headers_for() -> Callable[[User], dict[str, str]]:
    def _make(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token_for_user(user)}"}

    return _make
