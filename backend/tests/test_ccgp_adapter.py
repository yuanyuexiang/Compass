"""ccgp 适配器测试：fixture 为 2026-07-03 实抓的真实页面。"""

from datetime import datetime
from pathlib import Path

from app.crawler.adapters.ccgp import CcgpAdapter
from app.crawler.base import ADAPTERS, url_fingerprint

FIXTURES = Path(__file__).parent / "fixtures"
LIST_URL = "https://www.ccgp.gov.cn/cggg/zygg/"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_adapter_registered():
    import app.crawler.adapters  # noqa: F401

    assert "ccgp" in ADAPTERS


def test_parse_list_extracts_all_items():
    items = CcgpAdapter.parse_list(load("ccgp_list.html"), LIST_URL)
    assert len(items) == 20  # 每页 20 条


def test_parse_list_fields():
    first = CcgpAdapter.parse_list(load("ccgp_list.html"), LIST_URL)[0]
    assert first.title == "中国科学院金属研究所球差原位透射电镜采购项目单一来源采购公告"
    assert first.url.startswith("https://www.ccgp.gov.cn/cggg/zygg/")
    assert first.url.endswith(".htm")
    assert first.ann_type == "其他公告"
    assert first.publish_time == datetime(2026, 7, 3, 23, 6)
    assert first.region == "辽宁"
    assert first.buyer == "中国科学院金属研究所"


def test_parse_list_all_items_have_required_fields():
    for item in CcgpAdapter.parse_list(load("ccgp_list.html"), LIST_URL):
        assert item.title and item.url.startswith("https://")
        assert item.publish_time is not None


def test_url_fingerprint_stable_and_normalized():
    a = url_fingerprint("https://example.com/a.htm")
    assert a == url_fingerprint("https://example.com/a.htm#section")
    assert a != url_fingerprint("https://example.com/b.htm")
