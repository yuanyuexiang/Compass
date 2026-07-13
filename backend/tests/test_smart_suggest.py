"""smart-suggest 智能识别测试：域名匹配、静动判定、静态/动态分支（mock LLM 与浏览器）。"""

from app.ai import suggest as suggest_mod
from app.ai.suggest import looks_dynamic
from app.api.routes import sources as src

# 列表结构 + 足够可见文本（>500 字，避免被 looks_dynamic 判为 JS 壳）
LIST_HTML = (
    '<html><body><ul class="news-list">'
    '<li><a href="/zbgg/1.html" title="某工程施工招标公告">某工程施工招标公告</a>'
    '<span class="date">2026-07-13</span></li>'
    '<li><a href="/zbgg/2.html" title="某设备采购招标公告">某设备采购招标公告</a>'
    '<span class="date">2026-07-13</span></li>'
    '<li><a href="/zbgg/3.html" title="某服务采购招标公告">某服务采购招标公告</a>'
    '<span class="date">2026-07-13</span></li>'
    "</ul><div>" + "这里是页面的其他正文内容用于凑足可见文本长度。" * 30 + "</div></body></html>"
)


def test_looks_dynamic():
    assert looks_dynamic("<html><body></body></html>") is True  # 空壳
    obf = "<html><body>x</body><script>var _0xaaaa=1,_0xbbbb=2,_0xcccc=3;</script></html>"
    assert looks_dynamic(obf) is True  # 混淆脚本
    assert looks_dynamic("<html><body>" + "招标公告内容 " * 100 + "</body></html>") is False


def test_domain_match_routes_to_known(monkeypatch):
    called = {}

    def fake_known(adapter_name, url):
        called["adapter"] = adapter_name
        return {"ok": True, "adapter": adapter_name}

    monkeypatch.setattr(src, "_smart_known", fake_known)
    src.smart_suggest(src.SmartSuggestIn(url="https://www.ccgp.gov.cn/cggg/zygg/"), current=None)
    assert called["adapter"] == "ccgp"
    called.clear()
    js_url = "https://jsggzy.jszwfw.gov.cn/jyxx/x.html"
    src.smart_suggest(src.SmartSuggestIn(url=js_url), current=None)
    assert called["adapter"] == "jsggzy"


def test_unknown_domain_routes_to_generic(monkeypatch):
    called = {}

    def fake_generic(url):
        called["url"] = url
        return {"ok": True}

    monkeypatch.setattr(src, "_smart_generic", fake_generic)
    src.smart_suggest(src.SmartSuggestIn(url="https://some-unknown-site.gov.cn/list"), current=None)
    assert called["url"] == "https://some-unknown-site.gov.cn/list"


def test_static_route_generic(monkeypatch):
    """静态站：httpx 取到富文本 → 判静态 → generic + LLM 选择器 → 试采成功。"""
    import app.crawler.base as base_mod

    class FakeResp:
        text = LIST_HTML

    class FakeGeneric:
        def __init__(self, *a, **k):
            pass

        def get(self, url):
            return FakeResp()

        def fetch_detail(self, url):
            return "<div class='content'>" + "正文内容 " * 40 + "</div>"

        def content_selectors(self):
            return []

        def close(self):
            pass

    # _smart_generic 内部 `from app.crawler.base import get_adapter` → patch base 模块
    monkeypatch.setattr(base_mod, "get_adapter", lambda name, cfg=None: FakeGeneric())
    monkeypatch.setattr(
        suggest_mod, "suggest_list_selectors",
        lambda html, feedback=None: {"item_selector": "ul.news-list li", "link_selector": "a"},
    )
    monkeypatch.setattr(suggest_mod, "suggest_content_selector", lambda html: "div.content")

    res = src._smart_generic("https://x.gov.cn/list")
    assert res["adapter"] == "generic"
    assert res["ok"] is True
    assert len(res["items"]) == 3
    assert "静态" in res["notes"]
