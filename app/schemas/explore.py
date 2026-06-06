import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import PersonaCategory


class ExplorePersona(BaseModel):
    id: uuid.UUID
    name: str
    description_summary: str
    category: PersonaCategory
    github_repo_url: str | None
    published_at: datetime | None
    skill_names: list[str]


class ExploreResponse(BaseModel):
    personas: list[ExplorePersona]
    categories: list[PersonaCategory]
