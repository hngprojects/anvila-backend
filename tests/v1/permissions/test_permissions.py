"""
Permission dependency unit tests.

These test the four guard functions directly — no HTTP, no DB.
Each function accepts a User-like object and either returns it or raises HTTPException.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.deps import require_admin, require_can_generate, require_can_refine, require_pro
from app.models.enums import UserPlan


def _user(
    plan: UserPlan = UserPlan.FREE,
    generation_count: int = 0,
    refine_used: bool = False,
    is_admin: bool = False,
) -> MagicMock:
    u = MagicMock()
    u.plan = plan
    u.generation_count = generation_count
    u.refine_used = refine_used
    u.is_admin = is_admin
    return u


# ── require_can_generate ──────────────────────────────────────────────────────


def test_require_can_generate_free_at_limit_raises():
    with pytest.raises(HTTPException) as exc:
        require_can_generate(_user(plan=UserPlan.FREE, generation_count=3))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "GENERATION_LIMIT_REACHED"


def test_require_can_generate_free_above_limit_raises():
    with pytest.raises(HTTPException) as exc:
        require_can_generate(_user(plan=UserPlan.FREE, generation_count=10))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "GENERATION_LIMIT_REACHED"


def test_require_can_generate_free_under_limit_passes():
    u = _user(plan=UserPlan.FREE, generation_count=2)
    assert require_can_generate(u) is u


def test_require_can_generate_free_zero_passes():
    u = _user(plan=UserPlan.FREE, generation_count=0)
    assert require_can_generate(u) is u


def test_require_can_generate_paid_at_limit_passes():
    u = _user(plan=UserPlan.PAID, generation_count=3)
    assert require_can_generate(u) is u


def test_require_can_generate_paid_high_count_passes():
    u = _user(plan=UserPlan.PAID, generation_count=999)
    assert require_can_generate(u) is u


# ── require_can_refine ────────────────────────────────────────────────────────


def test_require_can_refine_free_used_raises():
    with pytest.raises(HTTPException) as exc:
        require_can_refine(_user(plan=UserPlan.FREE, refine_used=True))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "REFINE_LIMIT_REACHED"


def test_require_can_refine_free_not_used_passes():
    u = _user(plan=UserPlan.FREE, refine_used=False)
    assert require_can_refine(u) is u


def test_require_can_refine_paid_used_passes():
    u = _user(plan=UserPlan.PAID, refine_used=True)
    assert require_can_refine(u) is u


def test_require_can_refine_paid_not_used_passes():
    u = _user(plan=UserPlan.PAID, refine_used=False)
    assert require_can_refine(u) is u


# ── require_pro ───────────────────────────────────────────────────────────────


def test_require_pro_free_raises():
    with pytest.raises(HTTPException) as exc:
        require_pro(_user(plan=UserPlan.FREE))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "PRO_REQUIRED"


def test_require_pro_paid_passes():
    u = _user(plan=UserPlan.PAID)
    assert require_pro(u) is u


# ── require_admin ─────────────────────────────────────────────────────────────


def test_require_admin_non_admin_raises():
    with pytest.raises(HTTPException) as exc:
        require_admin(_user(is_admin=False))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "FORBIDDEN"


def test_require_admin_admin_passes():
    u = _user(is_admin=True)
    assert require_admin(u) is u
