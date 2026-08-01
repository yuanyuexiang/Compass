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


def test_clean_username():
    """用户名清洗：去首尾空白（含全角空格），中间空格拒绝（Johnson 尾空格事故复盘）。"""
    import pytest

    from app.api.routes.auth import LoginIn, RegisterIn, clean_username

    assert clean_username("Johnson ") == "Johnson"
    assert clean_username("　Johnson　") == "Johnson"  # 全角空格
    assert clean_username("Johnson") == "Johnson"
    with pytest.raises(ValueError):
        clean_username("John son")

    assert RegisterIn(
        tenant_name=" 某公司 ", username=" Johnson ", password="Abcd1234"
    ).username == "Johnson"
    assert LoginIn(username=" Johnson ", password="x").username == "Johnson"


def test_crypto_roundtrip_and_mask():
    """API Key 加密往返 + 脱敏展示 + 解密失败按未配置处理。"""
    from app.core.crypto import decrypt, encrypt, mask

    enc = encrypt("sk-abc123456789")
    assert enc.startswith("enc:") and "sk-abc" not in enc
    assert decrypt(enc) == "sk-abc123456789"
    assert decrypt("") == ""
    assert decrypt("enc:corrupted") == ""  # 密文损坏 → 空串（按未配置）
    assert decrypt("plain-legacy") == "plain-legacy"  # 历史明文兼容
    assert mask("sk-abc123456789") == "···6789"
    assert mask("short") == "···"
    assert mask("") == ""


def test_resolve_llm_target_precedence():
    """场景模型解析优先级：场景映射 > default 映射；fallback 需供应商存在。"""
    from app.ai.llm_config import (
        LlmConfigurationError,
        resolve_llm_fallback,
        resolve_llm_target,
    )

    cfg = {
        "providers": {
            "ds": {"api_key": "k1", "base_url": None},
            "qw": {"api_key": "k2", "base_url": "https://qw.example/v1"},
        },
        "scene_models": {
            "default": {"provider": "ds", "model": "deepseek/deepseek-v4-flash"},
            "match": {"provider": "qw", "model": "openai/qwen-plus"},
        },
        "fallback": {"provider": "qw", "model": "openai/qwen-plus"},
    }
    t = resolve_llm_target(cfg, "match")
    assert t["model"] == "openai/qwen-plus" and t["api_key"] == "k2"
    t = resolve_llm_target(cfg, "extract")  # 未映射场景走 default
    assert t["model"] == "deepseek/deepseek-v4-flash" and t["api_key"] == "k1"
    with pytest.raises(LlmConfigurationError):
        resolve_llm_target({"providers": {}, "scene_models": {}}, "match")
    fb = resolve_llm_fallback(cfg)
    assert fb and fb["base_url"] == "https://qw.example/v1"
    bad = {"providers": {}, "fallback": {"provider": "nope", "model": "x"}}
    assert resolve_llm_fallback(bad) is None


def test_blank_scene_model_is_accepted_as_incomplete_draft():
    from app.api.routes.admin import LlmConfigIn

    body = LlmConfigIn.model_validate(
        {"providers": [], "scene_models": {"extract": {"provider": "deepseek", "model": ""}}}
    )
    assert body.scene_models["extract"].model == ""
