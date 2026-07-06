import pytest
from fastapi import HTTPException

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
    user = get_current_user(FakeRequest(token))
    assert (user.user_id, user.tenant_id, user.role) == (7, 3, "sales")


def test_missing_or_bad_token_rejected():
    with pytest.raises(HTTPException):
        get_current_user(FakeRequest(None))
    with pytest.raises(HTTPException):
        get_current_user(FakeRequest("not-a-jwt"))
