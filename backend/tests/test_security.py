import time

import pytest
from fastapi import HTTPException

from app.core import security
from app.core.security import create_token, get_current_user, hash_password, verify_password


class FakeRequest:
    def __init__(self, token: str | None):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def test_password_hash_roundtrip():
    h = hash_password("admin123")
    assert verify_password("admin123", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip():
    token = create_token(user_id=7, tenant_id=3, role="sales")
    # 预热停用校验缓存以免触 DB（单测不依赖数据库；停用链路见 test_disabled_account_rejected）
    security._block_cache[7] = (time.monotonic() + 60, None)
    try:
        user = get_current_user(FakeRequest(token))
        assert (user.user_id, user.tenant_id, user.role) == (7, 3, "sales")
    finally:
        security.clear_block_cache(7)


def test_disabled_account_rejected():
    token = create_token(user_id=8, tenant_id=3, role="sales")
    security._block_cache[8] = (time.monotonic() + 60, "账号已停用")
    try:
        with pytest.raises(HTTPException) as exc:
            get_current_user(FakeRequest(token))
        assert exc.value.status_code == 401
        assert exc.value.detail == "账号已停用"
    finally:
        security.clear_block_cache(8)


def test_missing_or_bad_token_rejected():
    with pytest.raises(HTTPException):
        get_current_user(FakeRequest(None))
    with pytest.raises(HTTPException):
        get_current_user(FakeRequest("not-a-jwt"))
