import re
import uuid
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.paginator import PaginatedMeta

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ClarifyAnswer(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=4000)

    @field_validator("id")
    @classmethod
    def _id_must_be_snake_case(cls, v: str) -> str:
        if not _ID_PATTERN.match(v):
            raise ValueError("id must match snake_case [a-z][a-z0-9_]{0,63}")
        return v


class ClarifyRequest(BaseModel):
    session_id: UUID
    answers: list[ClarifyAnswer] = Field(min_length=1, max_length=10)


class ClarifyResponse(BaseModel):
    status: str
    round: int


class GenerateResponse(BaseModel):
    status: str
    persona_id: UUID
    session_id: UUID
    job_id: str


class SkillOut(BaseModel):
    slug: str
    name: str
    description: str
    tags: list[str]


class PersonaSummary(BaseModel):
    id: uuid.UUID
    name: str
    description_summary: str
    category: str
    status: str
    visibility: str
    github_repo_url: str | None
    created_at: datetime
    published_at: datetime | None


class PersonaListResponse(BaseModel):
    personas: list[PersonaSummary]
    meta: PaginatedMeta


class PersonaDetail(BaseModel):
    id: uuid.UUID
    name: str
    description_summary: str
    category: str
    status: str
    visibility: str
    github_repo_url: str | None
    github_clone_url: str | None
    github_zip_url: str | None
    published_at: datetime | None
    created_at: datetime
    identity_md: str | None
    soul_md: str | None
    dna_md: str | None
    overview_md: str | None
    heartbeat_md: str | None
    readme_md: str | None
    skills: list[SkillOut]


class PersonaStatusResponse(BaseModel):
    persona_id: uuid.UUID
    status: str
    files_completed: list[str]
    files_total: int
    skills_matched: bool
    name: str | None
    category: str | None
    description: str | None
    error_code: str | None


class PublishPersonaResponse(BaseModel):
    persona_id: str
    status: str
    published_at: datetime | None
    github_repo_url: str | None
    github_clone_url: str | None
    github_zip_url: str | None
