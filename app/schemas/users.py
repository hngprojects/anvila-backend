"""User-facing response schemas."""

from pydantic import BaseModel


class UserMeResponse(BaseModel):
    """Authenticated user's account and usage snapshot."""

    id: str
    plan: str
    generation_count: int
    generation_limit: int | None
    refine_used: bool
    github_connected: bool
    github_username: str | None
    total_tokens_used: int
