from httpx import AsyncClient

from app.models.user import User
from tests.v1.conftest import auth_headers

BASE = "/api/v1/users"


async def test_get_me_returns_correct_fields(client: AsyncClient, free_user: User):
    resp = await client.get(f"{BASE}/me", headers=auth_headers(free_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(free_user.id)
    assert data["plan"] == "free"
    assert data["generation_count"] == 0
    assert data["generation_limit"] == 3
    assert data["refine_used"] is False
    assert data["github_connected"] is False
    assert data["github_username"] is None
    assert data["total_tokens_used"] == 0


async def test_get_me_paid_user_has_null_limit(client: AsyncClient, paid_user: User):
    resp = await client.get(f"{BASE}/me", headers=auth_headers(paid_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "paid"
    assert data["generation_limit"] is None


async def test_get_me_unauthenticated(client: AsyncClient):
    resp = await client.get(f"{BASE}/me")
    assert resp.status_code == 401
