from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorDetail(BaseModel):
    message: str
    code: str | None = None
    field: str | None = None


class ApiResponse[T](BaseModel):
    success: bool = True
    message: str | None = None
    data: T | None = None
    meta: dict[str, Any] | None = None
