from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorDetail(BaseModel):
    message: str
    code: str | None = None
    field: str | None = None


# How to use:
#
# 1. Success Response with Data:
#    class UserResponse(BaseModel):
#        id: int
#        username: str
#
#    # In your endpoint:
#    user_data = UserResponse(id=1, username="muizzy")
#    return ApiResponse[UserResponse](data=user_data, message="User fetched successfully")
#
# 2. Plain Success Response (No Data):
#    return ApiResponse[None](success=True, message="Action completed")
#
# 3. Error Response:
#    err = ErrorDetail(message="Email already exists", code="DUPLICATE_EMAIL", field="email")
#    return ApiResponse[None](success=False, data=None, errors=[err])
#
# 4. Paginated List Response:
#    return ApiResponse[list[UserResponse]](
#        data=[user_data],
#        meta={"page": 1, "per_page": 10, "total": 1}
#    )
class ApiResponse[T](BaseModel):
    success: bool = True
    message: str | None = None
    data: T | None = None
    errors: list[ErrorDetail] | None = None
    meta: dict[str, Any] | None = None
