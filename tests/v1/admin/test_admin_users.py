from collections.abc import Callable
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserPlan
from app.models.user import User

BASE = "/api/v1/admin"


async def test_upgrade_user_sets_paid_plan(
    client: AsyncClient,
    admin_user: User,
    free_user: User,
    db_session: AsyncSession,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
        headers=auth_headers_for(admin_user),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan"] == "paid"
    assert data["upgraded_at"] is not None
    await db_session.refresh(free_user)
    assert free_user.plan == UserPlan.PAID
    assert free_user.upgraded_at is not None


async def test_upgrade_user_already_paid_preserves_timestamp(
    client: AsyncClient,
    admin_user: User,
    paid_user: User,
    db_session: AsyncSession,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(paid_user.id)},
        headers=auth_headers_for(admin_user),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan"] == "paid"
    assert data["upgraded_at"] is None
    await db_session.refresh(paid_user)
    assert paid_user.plan == UserPlan.PAID
    assert paid_user.upgraded_at is None


async def test_upgrade_user_repeat_call_preserves_timestamp(
    client: AsyncClient,
    admin_user: User,
    free_user: User,
    db_session: AsyncSession,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    first = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
        headers=auth_headers_for(admin_user),
    )
    assert first.status_code == 200
    await db_session.refresh(free_user)
    assert free_user.plan == UserPlan.PAID
    original_timestamp = free_user.upgraded_at
    assert original_timestamp is not None

    second = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
        headers=auth_headers_for(admin_user),
    )
    assert second.status_code == 200
    await db_session.refresh(free_user)
    assert free_user.upgraded_at == original_timestamp


async def test_upgrade_user_not_found_returns_404(
    client: AsyncClient,
    admin_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(uuid.uuid4())},
        headers=auth_headers_for(admin_user),
    )
    assert resp.status_code == 404


async def test_upgrade_user_requires_admin(
    client: AsyncClient,
    free_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
        headers=auth_headers_for(free_user),
    )
    assert resp.status_code == 403


async def test_upgrade_user_unauthenticated(client: AsyncClient, free_user: User) -> None:
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
    )
    assert resp.status_code == 401


async def test_list_users_returns_users_and_total(
    client: AsyncClient,
    admin_user: User,
    free_user: User,
    paid_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.get(f"{BASE}/users", headers=auth_headers_for(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    items = body["data"]
    total = body["meta"]["total"]
    assert total >= 3
    ids = {user["id"] for user in items}
    assert str(free_user.id) in ids
    assert str(paid_user.id) in ids


async def test_list_users_filter_free(
    client: AsyncClient,
    admin_user: User,
    free_user: User,
    paid_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.get(f"{BASE}/users?plan=free", headers=auth_headers_for(admin_user))
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert all(user["plan"] == "free" for user in items)
    assert str(paid_user.id) not in {user["id"] for user in items}


async def test_list_users_filter_paid(
    client: AsyncClient,
    admin_user: User,
    free_user: User,
    paid_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.get(f"{BASE}/users?plan=paid", headers=auth_headers_for(admin_user))
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert all(user["plan"] == "paid" for user in items)


async def test_list_users_pagination_limit(
    client: AsyncClient,
    admin_user: User,
    free_user: User,
    paid_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.get(f"{BASE}/users?page=1&size=1", headers=auth_headers_for(admin_user))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


async def test_list_users_pagination_offset(
    client: AsyncClient,
    admin_user: User,
    free_user: User,
    paid_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp_p1 = await client.get(f"{BASE}/users?page=1&size=1", headers=auth_headers_for(admin_user))
    resp_p2 = await client.get(f"{BASE}/users?page=2&size=1", headers=auth_headers_for(admin_user))
    assert resp_p1.status_code == 200
    assert resp_p2.status_code == 200
    p1_id = resp_p1.json()["data"][0]["id"]
    p2_id = resp_p2.json()["data"][0]["id"]
    assert p1_id != p2_id


async def test_list_users_requires_admin(
    client: AsyncClient,
    free_user: User,
    auth_headers_for: Callable[[User], dict[str, str]],
) -> None:
    resp = await client.get(f"{BASE}/users", headers=auth_headers_for(free_user))
    assert resp.status_code == 403


async def test_list_users_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get(f"{BASE}/users")
    assert resp.status_code == 401
