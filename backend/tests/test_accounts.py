"""账号体系单测：密码强度、平台管理员权限、注册入参、配额纯逻辑、路由前置校验。

DB/Redis 交互路径由浏览器级 E2E 与 dev 脚本覆盖，此处只测纯函数与进库前的守卫。
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.admin import _set_tenant_state
from app.api.routes.auth import RegisterIn
from app.api.routes.users import UserCreateIn, UserPatchIn, create_user, patch_user
from app.core.ratelimit import quota_key, try_consume_quota
from app.core.security import CurrentUser, require_platform_admin, validate_password


def test_validate_password():
    assert validate_password("short1") == "密码至少 8 位"
    assert validate_password("abcdefgh") == "密码需同时包含字母和数字"
    assert validate_password("12345678") == "密码需同时包含字母和数字"
    assert validate_password("abc12345") is None
    assert validate_password("Abc-1234!") is None


def test_require_platform_admin():
    user = require_platform_admin(CurrentUser(1, 1, "platform_admin"))
    assert user.role == "platform_admin"
    for role in ("tenant_admin", "sales"):
        with pytest.raises(HTTPException) as exc:
            require_platform_admin(CurrentUser(1, 1, role))
        assert exc.value.status_code == 403


def test_register_in_validation():
    with pytest.raises(ValidationError):
        RegisterIn(tenant_name="x", username="ab", password="abc12345")  # 企业名太短
    with pytest.raises(ValidationError):
        RegisterIn(tenant_name="某某公司", username="a", password="abc12345")  # 用户名太短
    body = RegisterIn(tenant_name="某某公司", username="boss", password="abc12345")
    assert body.email is None
    with_phone = RegisterIn(
        tenant_name="某某公司",
        username="boss2",
        password="abc12345",
        phone=" 138-0000-0000 ",
    )
    assert with_phone.phone == "138-0000-0000"
    with pytest.raises(ValidationError):
        RegisterIn(
            tenant_name="某某公司",
            username="boss3",
            password="abc12345",
            phone="13800000000x",
        )


def test_user_phone_validation():
    created = UserCreateIn(
        username="x1",
        password="abc12345",
        role="sales",
        phone="+86 13800000000",
    )
    assert created.phone == "+86 13800000000"
    patched = UserPatchIn(phone="")
    assert patched.phone is None
    with pytest.raises(ValidationError):
        UserCreateIn(username="x2", password="abc12345", role="sales", phone="call me")


def test_create_user_rejects_platform_admin_role():
    """角色校验在进库前完成：不允许经成员管理接口造平台管理员。"""
    with pytest.raises(HTTPException) as exc:
        create_user(UserCreateIn(username="x1", password="abc12345", role="platform_admin"),
                    CurrentUser(1, 1, "tenant_admin"))
    assert exc.value.status_code == 422


def test_create_user_rejects_weak_password():
    with pytest.raises(HTTPException) as exc:
        create_user(UserCreateIn(username="x1", password="123", role="sales"),
                    CurrentUser(1, 1, "tenant_admin"))
    assert exc.value.status_code == 422


def test_patch_user_rejects_invalid_role():
    with pytest.raises(HTTPException) as exc:
        patch_user(2, UserPatchIn(role="platform_admin"), CurrentUser(1, 1, "tenant_admin"))
    assert exc.value.status_code == 422


def test_disable_own_tenant_rejected():
    """平台管理员不能停用自己所在租户（防自锁），校验在进库前完成。"""
    with pytest.raises(HTTPException) as exc:
        _set_tenant_state(7, CurrentUser(1, 7, "platform_admin"), status="disabled", enabled=False)
    assert exc.value.status_code == 422


def test_platform_tenant_protected():
    """平台租户（admin 挂靠处）不可停用/删除；业务租户不受影响。"""
    from types import SimpleNamespace

    from app.api.routes.admin import _reject_platform_tenant

    with pytest.raises(HTTPException) as exc:
        _reject_platform_tenant(SimpleNamespace(is_platform=True), "停用")
    assert exc.value.status_code == 422 and "平台租户" in exc.value.detail
    _reject_platform_tenant(SimpleNamespace(is_platform=False), "删除")  # 业务租户放行


def test_quota_key_beijing_day():
    # UTC 2026-07-20 20:00 = 北京时间 2026-07-21 04:00，日界按北京时间
    now = datetime(2026, 7, 20, 20, 0, tzinfo=UTC)
    assert quota_key("match", 3, now) == "quota:match:3:20260721"


def test_quota_unlimited_short_circuit():
    # limit<=0 = 不限量，不触碰 Redis（传入非法 tenant 也应直接放行）
    assert try_consume_quota(999999, "nl_search", 0) is True
    assert try_consume_quota(999999, "nl_search", -1) is True
