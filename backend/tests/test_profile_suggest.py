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


def test_bid_snippet():
    """公告正文按企业名截取证据片段；未命中给开头；空文本给空串。"""
    from app.ai.profile_suggest import bid_snippet

    text = "A" * 300 + "某某科技有限公司" + "B" * 300
    snip = bid_snippet(text, "某某科技有限公司")
    assert "某某科技有限公司" in snip and len(snip) <= 260
    assert bid_snippet("短文本", "不存在的名字") == "短文本"
    assert bid_snippet(None, "x") == ""
    assert bid_snippet("有换行\n的文本某公司在这", "某公司") == "有换行 的文本某公司在这"


def test_confidence_of():
    """置信度按信源覆盖度：官网+中标→high；任一→medium；全空→low。"""
    from app.ai.profile_suggest import confidence_of

    assert confidence_of("官网文本", [{"t": 1}], []) == "high"
    assert confidence_of("官网文本", [], []) == "medium"
    assert confidence_of(None, [{"t": 1}], []) == "medium"
    assert confidence_of(None, [], [{"t": 1}]) == "medium"
    assert confidence_of(None, [], []) == "low"
