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
