from datetime import datetime

import pytest

from app.crawler.adapters.generic import GenericAdapter, parse_date

LIST_HTML = """
<html><body>
<ul class="news-list">
  <li><a href="/zbgg/1.html" title="某学校教学楼装修工程招标公告">某学校教学楼装修…</a>
      <span class="date">2026-07-08</span></li>
  <li><a href="detail/2.html">某医院医疗设备采购项目公开招标公告</a> 发布于 2026年7月7日</li>
  <li><a href="/more">更多</a></li>
  <li><span>没有链接的条目</span></li>
</ul>
</body></html>
"""

BASE = "https://example.gov.cn/zbgg/index.html"


def test_parse_date_variants():
    assert parse_date("2026-07-08") == datetime(2026, 7, 8)
    assert parse_date("发布时间：2026年7月8日") == datetime(2026, 7, 8)
    assert parse_date("2026/7/8 10:30") == datetime(2026, 7, 8)
    assert parse_date("2026.07.08") == datetime(2026, 7, 8)
    assert parse_date("无日期") is None
    assert parse_date("2026-13-40") is None  # 伪日期不炸


def test_parse_list_with_date_selector():
    config = {"item_selector": "ul.news-list li", "date_selector": "span.date", "region": "江苏省"}
    items = GenericAdapter.parse_list(LIST_HTML, BASE, config)
    # 「更多」（标题过短）和无链接条目被过滤
    assert len(items) == 2
    first = items[0]
    assert first.title == "某学校教学楼装修工程招标公告"  # 优先取 a[title]
    assert first.url == "https://example.gov.cn/zbgg/1.html"  # 绝对路径 join
    assert first.publish_time == datetime(2026, 7, 8)
    assert first.region == "江苏省"


def test_parse_list_date_fallback_to_item_text():
    config = {"item_selector": "ul.news-list li"}  # 不配 date_selector → 条目全文找日期
    items = GenericAdapter.parse_list(LIST_HTML, BASE, config)
    assert items[1].title == "某医院医疗设备采购项目公开招标公告"
    assert items[1].url == "https://example.gov.cn/zbgg/detail/2.html"  # 相对路径 join
    assert items[1].publish_time == datetime(2026, 7, 7)


def test_bad_date_selector_falls_back_to_item_text():
    # 配了错误的日期选择器（匹配不到）→ 回退全文，仍能取到日期（修复 AI 生成位置选择器的场景）
    config = {"item_selector": "ul.news-list li", "date_selector": "span.wrong-class"}
    items = GenericAdapter.parse_list(LIST_HTML, BASE, config)
    assert items[0].publish_time == datetime(2026, 7, 8)


def test_missing_required_config():
    with pytest.raises(ValueError, match="item_selector"):
        GenericAdapter.parse_list(LIST_HTML, BASE, {})
    adapter = GenericAdapter({})
    with pytest.raises(ValueError, match="list_url"):
        next(adapter.list_announcements())
