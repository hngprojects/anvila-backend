from pydantic import BaseModel, Field
from uuid import UUID

class SkillRead(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    content: str
    category: str | None = None
    tags: list[str] | None = None
    source_registry: str
    source_url: str | None = None
    source_author: str | None = None
    install_count: int
    is_active: bool

    model_config = {"from_attributes": True}


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=220)
    description: str
    content: str
    category: str | None = None
    tags: list[str] | None = None


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None