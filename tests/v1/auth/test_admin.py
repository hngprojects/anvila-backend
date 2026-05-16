from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

BASE_AUTH = "/api/v1/auth"
BASE_ADMIN = "/api/v1/admin"


async def _create_verified_user_with_tokens(
    client: AsyncClient,
    db: AsyncSession,
    email: str,
    password: str = "ValidPass1!",
) -> tuple[User, str, str]:
    await client.post(f"{BASE_AUTH}/register", json={"email": email, "password": password})

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    user.email_verified = True
    await db.commit()

    resp = await client.post(f"{BASE_AUTH}/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    tokens = resp.json()["tokens"]
    return user, tokens["access_token"], tokens["refresh_token"]


async def _make_admin(db: AsyncSession, user: User) -> User:
    user.is_admin = True
    await db.commit()
    await db.refresh(user)
    return user


async def _make_super_admin(db: AsyncSession, user: User) -> User:
    user.is_super_admin = True
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Admin dependency tests
# ---------------------------------------------------------------------------


async def test_admin_dashboard_as_admin(client: AsyncClient, db_session: AsyncSession):
    user, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="admin_dash@test.com"
    )
    await _make_admin(db_session, user)

    resp = await client.get(
        f"{BASE_ADMIN}/dashboard", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "admin_email" in data["data"]
    assert data["data"]["admin_email"] == "admin_dash@test.com"


async def test_admin_dashboard_as_super_admin(client: AsyncClient, db_session: AsyncSession):
    user, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="super_dash@test.com"
    )
    await _make_super_admin(db_session, user)

    resp = await client.get(
        f"{BASE_ADMIN}/dashboard", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_admin_dashboard_as_regular_user(client: AsyncClient, db_session: AsyncSession):
    _, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="regular_dash@test.com"
    )

    resp = await client.get(
        f"{BASE_ADMIN}/dashboard", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 403


async def test_admin_dashboard_unauthenticated(client: AsyncClient):
    resp = await client.get(f"{BASE_ADMIN}/dashboard")
    assert resp.status_code == 401


async def test_admin_dashboard_with_invalid_token(client: AsyncClient):
    resp = await client.get(
        f"{BASE_ADMIN}/dashboard", headers={"Authorization": "Bearer invalidtoken"}
    )
    assert resp.status_code == 401


async def test_admin_dashboard_with_refresh_token(client: AsyncClient, db_session: AsyncSession):
    user, _, raw_refresh = await _create_verified_user_with_tokens(
        client, db_session, email="admin_refresh@test.com"
    )
    await _make_admin(db_session, user)

    resp = await client.get(
        f"{BASE_ADMIN}/dashboard", headers={"Authorization": f"Bearer {raw_refresh}"}
    )
    assert resp.status_code == 401


async def test_admin_me_as_admin(client: AsyncClient, db_session: AsyncSession):
    user, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="admin_me@test.com"
    )
    await _make_admin(db_session, user)

    resp = await client.get(
        f"{BASE_ADMIN}/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_admin"] is True
    assert data["is_super_admin"] is False


async def test_admin_me_as_regular_user(client: AsyncClient, db_session: AsyncSession):
    _, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="regular_me@test.com"
    )

    resp = await client.get(
        f"{BASE_ADMIN}/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 403


async def test_admin_dependency_is_admin_or_super_admin(
    client: AsyncClient, db_session: AsyncSession
):
    user, access_token, _ = await _create_verified_user_with_tokens(
        client, db_session, email="super_only@test.com"
    )
    # Only super_admin set — is_admin remains False
    await _make_super_admin(db_session, user)

    resp = await client.get(
        f"{BASE_ADMIN}/dashboard", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resp.status_code == 200


async def test_regular_user_cannot_elevate_to_admin(client: AsyncClient, db_session: AsyncSession):
    user, _, _ = await _create_verified_user_with_tokens(
        client, db_session, email="elevate@test.com"
    )
    # Craft a JWT with is_admin=True but signed with wrong secret
    fake_token = jwt.encode(
        {"sub": str(user.id), "is_admin": True, "purpose": "access"},
        "wrong-secret-that-is-at-least-32-characters-long",
        algorithm="HS256",
    )

    resp = await client.get(
        f"{BASE_ADMIN}/dashboard", headers={"Authorization": f"Bearer {fake_token}"}
    )
    assert resp.status_code == 401
