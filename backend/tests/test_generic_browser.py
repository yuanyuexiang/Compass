"""通用动态站适配器测试：验证注册、继承解析逻辑、取页面走浏览器渲染（mock 渲染，免真实浏览器）。"""

from datetime import datetime

from app.crawler.adapters.generic_browser import GenericBrowserAdapter
from app.crawler.base import ADAPTERS

LIST_HTML = """
<html><body><ul class="news-list">
  <li><a href="/zbgg/1.html" title="某数据中心机房建设项目招标公告">某数据中心…</a>
      <span class="date">2026-07-08</span></li>
</ul></body></html>
"""


def test_registered():
    import app.crawler.adapters  # noqa: F401

    assert "generic_browser" in ADAPTERS
    assert ADAPTERS["generic_browser"].display_name == "通用网站（动态渲染 / JS）"


def test_uses_browser_render_not_httpx(monkeypatch):
    """_text 应调用浏览器 render（而非 httpx get），并把 wait_selector 透传。"""
    calls = {}

    def fake_render(self, url, wait_selector=None):
        calls["url"] = url
        calls["wait_selector"] = wait_selector
        return LIST_HTML

    monkeypatch.setattr(GenericBrowserAdapter, "render", fake_render)
    ad = GenericBrowserAdapter({
        "list_url": "https://js-site.example.com/list",
        "item_selector": "ul.news-list li",
        "wait_selector": "ul.news-list",
    })
    items = list(ad.list_announcements())
    assert calls["url"] == "https://js-site.example.com/list"
    assert calls["wait_selector"] == "ul.news-list"  # wait_selector 透传给渲染
    assert len(items) == 1
    assert items[0].title == "某数据中心机房建设项目招标公告"
    assert items[0].publish_time == datetime(2026, 7, 8)


def test_inherits_generic_parse(monkeypatch):
    """继承 generic 的解析：过滤短标题、绝对化 URL。"""
    monkeypatch.setattr(
        GenericBrowserAdapter, "render", lambda self, url, wait_selector=None: LIST_HTML
    )
    ad = GenericBrowserAdapter({"list_url": "https://x.cn/a/", "item_selector": "ul.news-list li"})
    items = list(ad.list_announcements())
    assert items[0].url == "https://x.cn/zbgg/1.html"
