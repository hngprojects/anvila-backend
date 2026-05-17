from httpx import AsyncClient

BASE = "/api/v1/auth"


async def test_google_start_returns_307_with_state_cookie(client: AsyncClient):
    """GET /auth/google issues a 307 redirect and sets the oauth_state cookie."""
    resp = await client.get(f"{BASE}/google", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers.get("location", "")
    assert "accounts.google.com" in location
    set_cookie = resp.headers.get("set-cookie", "")
    assert "oauth_state=" in set_cookie
