"""江苏公共资源交易平台适配器测试：fixture 为 2026-07-07 实测的真实接口响应与详情页。"""

import json
from datetime import datetime
from pathlib import Path

from app.crawler.adapters.jsggzy import DEFAULT_CATEGORYNUMS, JsggzyAdapter, _search_payload
from app.parsing.clean import html_to_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_records_fields():
    data = json.loads((FIXTURES / "jsggzy_list.json").read_text(encoding="utf-8"))
    items = JsggzyAdapter.parse_records(data)
    assert len(items) == 3
    first = items[0]
    assert first.title.startswith("育德路")
    assert first.url.startswith("https://jsggzy.jszwfw.gov.cn/jyxx/003001/003001001/")
    assert first.publish_time == datetime(2026, 7, 7, 0, 0, 0)
    assert first.extra["categorynum"] == "003001001"


def test_search_payload_sorted_by_date_desc():
    payload = _search_payload("003004002", 20)
    assert payload["sort"] == '{"infodatepx":"0"}'
    assert payload["condition"][0]["equal"] == "003004002"
    assert payload["rn"] == 20


def test_default_categories_cover_seven_boards():
    assert len(DEFAULT_CATEGORYNUMS) == 7
    assert "003004002" in DEFAULT_CATEGORYNUMS  # 政府采购


def test_clean_detail_page():
    html = (FIXTURES / "jsggzy_detail.html").read_text(encoding="utf-8")
    text = html_to_text(html, JsggzyAdapter().content_selectors())
    assert "苏州实验中学" in text
    assert len(text) > 300


def test_browser_mode_default_and_parse(monkeypatch):
    """默认走浏览器模式：mock fetch_json_via_page 返回接口 JSON，验证按类目解析。"""
    from app.crawler import browser

    data = json.loads((FIXTURES / "jsggzy_list.json").read_text(encoding="utf-8"))
    called = {}

    def fake_fetch(nav_url, api_url, payloads, **kw):
        called["nav"] = nav_url
        called["n"] = len(payloads)
        return [{"ok": True, "json": data} for _ in payloads]

    monkeypatch.setattr(browser, "fetch_json_via_page", fake_fetch)
    # 只配 2 个类目，便于断言 payload 数
    ad = JsggzyAdapter({"categorynums": ["003001001", "003004002"], "rows_per_category": 3})
    items = list(ad.list_announcements())
    assert called["nav"].endswith("/jyxx/tradeInfonew.html")  # 先导航列表页过挑战
    assert called["n"] == 2  # 两个类目 → 两个 payload
    assert len(items) == 6  # 每类目解析出 3 条
    assert items[0].title.startswith("育德路")


def test_httpx_fallback_when_disabled(monkeypatch):
    """use_browser=false 时回退纯 httpx（不碰浏览器）。"""
    data = json.loads((FIXTURES / "jsggzy_list.json").read_text(encoding="utf-8"))

    class FakeResp:
        def json(self):
            return data

    ad = JsggzyAdapter(
        {"use_browser": False, "categorynums": ["003001001"], "rows_per_category": 3}
    )
    monkeypatch.setattr(ad, "post_json", lambda url, payload: FakeResp())
    items = list(ad.list_announcements())
    assert len(items) == 3
