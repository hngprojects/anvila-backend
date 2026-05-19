import uuid

from httpx import AsyncClient

from app.models.user import User
from tests.v1.conftest import auth_headers

BASE = "/api/v1/admin"


# ── POST /admin/users/upgrade ─────────────────────────────────────────────────


async def test_upgrade_user_sets_paid_plan(
    client: AsyncClient, admin_user: User, free_user: User
):
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "paid"
    assert data["upgraded_at"] is not None


async def test_upgrade_user_not_found_returns_404(client: AsyncClient, admin_user: User):
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(uuid.uuid4())},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 404


async def test_upgrade_user_requires_admin(client: AsyncClient, free_user: User):
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
        headers=auth_headers(free_user),
    )
    assert resp.status_code == 403


async def test_upgrade_user_unauthenticated(client: AsyncClient, free_user: User):
    resp = await client.post(
        f"{BASE}/users/upgrade",
        json={"user_id": str(free_user.id)},
    )
    assert resp.status_code == 401


# ── GET /admin/users ──────────────────────────────────────────────────────────


async def test_list_users_returns_users_and_total(
    client: AsyncClient, admin_user: User, free_user: User, paid_user: User
):
    resp = await client.get(f"{BASE}/users", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert "users" in data
    assert "total" in data
    assert data["total"] >= 3
    ids = {u["id"] for u in data["users"]}
    assert str(free_user.id) in ids
    assert str(paid_user.id) in ids


async def test_list_users_filter_free(
    client: AsyncClient, admin_user: User, free_user: User, paid_user: User
):
    resp = await client.get(f"{BASE}/users?plan=free", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert all(u["plan"] == "free" for u in data["users"])
    assert str(paid_user.id) not in {u["id"] for u in data["users"]}


async def test_list_users_filter_paid(
    client: AsyncClient, admin_user: User, free_user: User, paid_user: User
):
    resp = await client.get(f"{BASE}/users?plan=paid", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert all(u["plan"] == "paid" for u in data["users"])


async def test_list_users_pagination_limit(
    client: AsyncClient, admin_user: User, free_user: User, paid_user: User
):
    resp = await client.get(f"{BASE}/users?page=1&size=1", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert len(resp.json()["users"]) == 1


async def test_list_users_pagination_offset(
    client: AsyncClient, admin_user: User, free_user: User, paid_user: User
):
    resp_all = await client.get(f"{BASE}/users?size=100", headers=auth_headers(admin_user))
    all_ids = [u["id"] for u in resp_all.json()["users"]]

    resp_page = await client.get(
        f"{BASE}/users?page=2&size=1", headers=auth_headers(admin_user)
    )
    page_ids = [u["id"] for u in resp_page.json()["users"]]
    assert page_ids[0] == all_ids[1]


async def test_list_users_requires_admin(client: AsyncClient, free_user: User):
    resp = await client.get(f"{BASE}/users", headers=auth_headers(free_user))
    assert resp.status_code == 403


async def test_list_users_unauthenticated(client: AsyncClient):
    resp = await client.get(f"{BASE}/users")
    assert resp.status_code == 401
