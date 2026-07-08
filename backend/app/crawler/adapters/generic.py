"""通用网站适配器：面向「列表页 + 详情页」结构的招标网站，差异全部经 config 配置，无需写代码。

config 字段：
    list_url          必填，公告列表页地址
    item_selector     必填，每条公告的 CSS 选择器（如 "ul.news-list li"）
    link_selector     可选，条目内链接选择器（默认 "a"），href→详情地址、title/文本→标题
    date_selector     可选，条目内日期元素选择器；缺省时在条目全文中自动找日期
    content_selector  可选，详情页正文容器选择器（供清洗使用，强烈建议配置）
    region            可选，站点所属地区静态标注（如 "江苏省"）
    encoding          可选，老站点可配 "gbk"

适配范围：静态渲染的规整站点。JS 渲染/反爬站仍需专用适配器（tech-design §4.1）。
"""

import re
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.crawler.base import RawAnnouncement, SourceAdapter, register

# 支持 2026-07-08 / 2026/7/8 / 2026年7月8日 / 2026.07.08
_DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")


def parse_date(text: str | None) -> datetime | None:
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:  # 如 2026-13-40 之类的伪日期
        return None


@register
class GenericAdapter(SourceAdapter):
    name = "generic"
    display_name = "通用网站（配置选择器）"

    @staticmethod
    def parse_list(html: str, base_url: str, config: dict) -> list[RawAnnouncement]:
        item_selector = config.get("item_selector")
        if not item_selector:
            raise ValueError("generic 适配器需要 config.item_selector")
        soup = BeautifulSoup(html, "lxml")
        items: list[RawAnnouncement] = []
        for el in soup.select(item_selector):
            a = el.select_one(config.get("link_selector") or "a")
            if a is None or not a.get("href"):
                continue
            title = (a.get("title") or a.get_text(strip=True) or "").strip()
            if len(title) < 5:  # 过滤「更多」「下一页」等噪声链接
                continue
            publish_time = None
            if date_selector := config.get("date_selector"):
                date_el = el.select_one(date_selector)
                if date_el:
                    publish_time = parse_date(date_el.get_text(" ", strip=True))
            # 未配 date_selector，或选择器取不到有效日期时，回退到条目全文找日期
            if publish_time is None:
                publish_time = parse_date(el.get_text(" ", strip=True))
            items.append(
                RawAnnouncement(
                    url=urljoin(base_url, a["href"]),
                    title=title,
                    publish_time=publish_time,
                    region=config.get("region"),
                )
            )
        return items

    def _text(self, url: str) -> str:
        resp = self.get(url)
        if encoding := self.config.get("encoding"):
            return resp.content.decode(encoding, errors="replace")
        return resp.text

    def list_announcements(self, since: datetime | None = None) -> Iterator[RawAnnouncement]:
        list_url = self.config.get("list_url")
        if not list_url:
            raise ValueError("generic 适配器需要 config.list_url")
        for item in self.parse_list(self._text(list_url), list_url, self.config):
            if since and item.publish_time and item.publish_time <= since:
                continue  # 通用站点不保证列表有序，用 continue 而非 break
            yield item

    def fetch_detail(self, url: str) -> str:
        return self._text(url)

    def content_selectors(self) -> list[str]:
        selector = self.config.get("content_selector")
        return [selector] if selector else []
