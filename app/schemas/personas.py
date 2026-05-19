import re
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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
