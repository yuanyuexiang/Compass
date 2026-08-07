"""模型供应商连接测试接口的错误边界。"""

from contextlib import contextmanager

from app.ai import llm_config
from app.api.routes import admin
from app.core import crypto, kv


@contextmanager
def _fake_session_scope():
    yield object()


def test_llm_connection_test_converts_unexpected_error_to_result(monkeypatch):
    """配置读取和调用链的意外异常也应返回可读结果，不能冒泡成 HTTP 500。"""
    monkeypatch.setattr(admin, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        kv,
        "get_setting",
        lambda *_args, **_kwargs: [
            {"name": "mimo", "api_key": "encrypted", "base_url": "https://example.test/v1"}
        ],
    )
    monkeypatch.setattr(crypto, "decrypt", lambda _value: "sk-test")
    monkeypatch.setattr(
        llm_config,
        "extract_completion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    result = admin.test_llm_provider(
        admin.LlmSceneModelIn(provider="mimo", model="openai/mimo-v2.5-pro"),
        current=object(),
    )

    assert result == {
        "ok": False,
        "message": "连接测试失败，请检查 Base URL、模型名和服务端日志",
    }


def test_custom_base_url_automatically_uses_openai_adapter(monkeypatch):
    """自定义 OpenAI 兼容网关接受供应商原始模型 ID，无需用户理解 LiteLLM 前缀。"""
    captured = {}
    monkeypatch.setattr(
        llm_config.litellm,
        "completion",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    llm_config._call(
        {
            "model": "moonshotai/kimi-k3-free",
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1",
        },
        [{"role": "user", "content": "hello"}],
    )

    assert captured["model"] == "openai/moonshotai/kimi-k3-free"
    assert captured["api_base"] == "https://api.example.test/v1"


def test_mimo_empty_base_url_uses_official_endpoint():
    assert (
        llm_config.provider_base_url("mimo", "")
        == "https://api.xiaomimimo.com/v1"
    )


def test_admin_test_does_not_clear_extract_failure_streak(monkeypatch):
    """测试其他供应商成功不等于正式字段提取恢复。"""
    resets = []
    monkeypatch.setattr(llm_config, "_load_llm_config", lambda: {})
    monkeypatch.setattr(llm_config, "_call", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("app.core.ratelimit.counter_reset", lambda key: resets.append(key))
    monkeypatch.setattr("app.core.ratelimit.note_delete", lambda _key: None)

    llm_config.extract_completion(
        messages=[],
        scene="admin_test",
        model_override={"model": "openai/test", "api_key": "sk-test", "base_url": None},
    )

    assert resets == []
