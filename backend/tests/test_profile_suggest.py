"""AI 企业画像草稿测试：秘塔来源合规过滤、LLM 输出宽容解析、无结果/异常降级（mock 搜索与 LLM）。"""

import types

from app.ai import profile_suggest, websearch


def _fake_completion(content: str):
    """构造 litellm 风格返回对象：resp.choices[0].message.content。"""
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
    )


def test_websearch_blocks_aggregators(monkeypatch):
    payload = {
        "webpages": [
            {"title": "官网", "link": "https://company.example.com/x", "snippet": "s1"},
            {"title": "天眼查", "link": "https://www.tianyancha.com/company/1", "snippet": "s2"},
            {"title": "企查查", "link": "https://www.qcc.com/firm/abc", "snippet": "s3"},
        ]
    }

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    monkeypatch.setattr(websearch.settings, "metaso_api_key", "mk-test")
    monkeypatch.setattr(websearch.httpx, "post", lambda *a, **k: FakeResp())
    links = [r["link"] for r in websearch.search("x")]
    assert "https://company.example.com/x" in links
    assert all("tianyancha" not in link and "qcc.com" not in link for link in links)


def test_suggest_profile_parses_fenced_json(monkeypatch):
    monkeypatch.setattr(
        profile_suggest.websearch,
        "search",
        lambda *a, **k: [{"title": "官网", "link": "https://e.com", "snippet": "主营云计算"}],
    )
    llm_out = (
        "```json\n"
        '{"name":"示例科技有限公司","description":"云计算服务商","products":["私有云平台"],'
        '"services":["运维"],"industries":["信息技术"],"certifications":[],"brands":[],'
        '"cases_text":"","_sources":["https://e.com"],"_confidence":"medium","_note":"请核对资质"}'
        "\n```"
    )
    monkeypatch.setattr(
        profile_suggest, "extract_completion", lambda **k: _fake_completion(llm_out)
    )
    r = profile_suggest.suggest_profile("示例科技有限公司")
    assert r["draft"]["name"] == "示例科技有限公司"
    assert r["draft"]["products"] == ["私有云平台"]
    assert "certifications" not in r["draft"]  # 空值不带入草稿
    assert r["confidence"] == "medium"
    assert r["sources"] == ["https://e.com"]


def test_suggest_profile_no_search_results(monkeypatch):
    monkeypatch.setattr(profile_suggest.websearch, "search", lambda *a, **k: [])
    r = profile_suggest.suggest_profile("查无此企业")
    assert r["draft"] == {"name": "查无此企业"}
    assert r["confidence"] == "low"


def test_suggest_profile_fallback_on_garbage(monkeypatch):
    monkeypatch.setattr(
        profile_suggest.websearch,
        "search",
        lambda *a, **k: [{"title": "t", "link": "https://e.com", "snippet": "s"}],
    )
    monkeypatch.setattr(
        profile_suggest, "extract_completion", lambda **k: _fake_completion("抱歉，无法解析")
    )
    r = profile_suggest.suggest_profile("某公司")
    assert r["draft"]["name"] == "某公司"  # 解析失败仍兜底企业名
    assert r["confidence"] == "low"
    assert r["sources"] == ["https://e.com"]
