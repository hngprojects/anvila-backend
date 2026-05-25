from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps import (
    get_current_admin,
    require_can_generate,
    require_can_refine,
    require_pro,
)
from app.models.enums import UserPlan


def _user(
    plan: UserPlan = UserPlan.FREE,
    generation_count: int = 0,
    refine_used: bool = False,
    is_admin: bool = False,
    is_super_admin: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        plan=plan,
        generation_count=generation_count,
        refine_used=refine_used,
        is_admin=is_admin,
        is_super_admin=is_super_admin,
    )


def test_require_can_generate_free_at_limit_raises() -> None:
    with pytest.raises(HTTPException) as exc:
        require_can_generate(_user(plan=UserPlan.FREE, generation_count=3))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "GENERATION_LIMIT_REACHED"


def test_require_can_generate_free_above_limit_raises() -> None:
    with pytest.raises(HTTPException) as exc:
        require_can_generate(_user(plan=UserPlan.FREE, generation_count=10))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "GENERATION_LIMIT_REACHED"


def test_require_can_generate_free_under_limit_passes() -> None:
    user = _user(plan=UserPlan.FREE, generation_count=2)
    assert require_can_generate(user) is user


def test_require_can_generate_free_zero_passes() -> None:
    user = _user(plan=UserPlan.FREE, generation_count=0)
    assert require_can_generate(user) is user


def test_require_can_generate_paid_at_limit_passes() -> None:
    user = _user(plan=UserPlan.PAID, generation_count=3)
    assert require_can_generate(user) is user


def test_require_can_generate_paid_high_count_passes() -> None:
    user = _user(plan=UserPlan.PAID, generation_count=999)
    assert require_can_generate(user) is user


def test_require_can_refine_free_used_raises() -> None:
    with pytest.raises(HTTPException) as exc:
        require_can_refine(_user(plan=UserPlan.FREE, refine_used=True))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "REFINE_LIMIT_REACHED"


def test_require_can_refine_free_not_used_passes() -> None:
    user = _user(plan=UserPlan.FREE, refine_used=False)
    assert require_can_refine(user) is user


def test_require_can_refine_paid_used_passes() -> None:
    user = _user(plan=UserPlan.PAID, refine_used=True)
    assert require_can_refine(user) is user


def test_require_can_refine_paid_not_used_passes() -> None:
    user = _user(plan=UserPlan.PAID, refine_used=False)
    assert require_can_refine(user) is user


def test_require_pro_free_raises() -> None:
    with pytest.raises(HTTPException) as exc:
        require_pro(_user(plan=UserPlan.FREE))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "PRO_REQUIRED"


def test_require_pro_paid_passes() -> None:
    user = _user(plan=UserPlan.PAID)
    assert require_pro(user) is user


async def test_get_current_admin_non_admin_raises() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_current_admin(_user(is_admin=False))
    assert exc.value.status_code == 403
    assert exc.value.detail == "Admin access required"


async def test_get_current_admin_admin_passes() -> None:
    user = _user(is_admin=True, is_super_admin=False)
    assert await get_current_admin(user) is user


async def test_get_current_admin_super_admin_passes() -> None:
    user = _user(is_admin=False, is_super_admin=True)
    assert await get_current_admin(user) is user
