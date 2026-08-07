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
