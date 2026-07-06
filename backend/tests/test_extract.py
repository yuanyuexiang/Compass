"""提取模块单测：mock LLM 响应，验证校验/重试逻辑（真实调用见 scripts/dev_extract.py）。"""

import json
from types import SimpleNamespace

import pytest

from app.ai import extract as extract_mod
from app.ai.extract import ExtractionError, build_input, extract_project

VALID_FIELD = {"value": "测试值", "evidence": "原文", "confidence": 0.95}
VALID_RESULT = {
    name: VALID_FIELD
    for name in [
        "project_name", "tender_org", "publish_time", "bid_deadline", "budget",
        "industry", "region", "product_category", "service_type", "contact",
        "attachments_info", "requirements",
    ]
} | {
    "classification": {"main": "IT类", "sub": "服务器", "confidence": 0.9},
    "summary": "某地采购服务器一批",
}


def fake_response(content: str | None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_extract_success(monkeypatch):
    monkeypatch.setattr(
        extract_mod, "extract_completion", lambda **kw: fake_response(json.dumps(VALID_RESULT))
    )
    result = extract_project("公告全文")
    assert result.project_name.value == "测试值"
    assert result.classification.main == "IT类"
    assert result.summary == "某地采购服务器一批"


def test_retry_on_empty_then_succeed(monkeypatch):
    responses = iter([fake_response(""), fake_response(json.dumps(VALID_RESULT))])
    monkeypatch.setattr(extract_mod, "extract_completion", lambda **kw: next(responses))
    assert extract_project("公告全文").budget.value == "测试值"


def test_fail_after_max_attempts(monkeypatch):
    monkeypatch.setattr(extract_mod, "extract_completion", lambda **kw: fake_response("不是json"))
    with pytest.raises(ExtractionError, match="连续 3 次"):
        extract_project("公告全文")


def test_build_input_includes_attachments_and_truncates():
    text = build_input("标题", "正文", ["附件文本"])
    assert "【公告标题】标题" in text and "【附件1正文】" in text
    assert len(build_input("t", "x" * 100_000)) <= extract_mod.MAX_INPUT_CHARS
