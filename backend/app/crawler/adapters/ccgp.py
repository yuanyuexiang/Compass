"""中国政府采购网（ccgp.gov.cn）适配器。

页面结构（2026-07 实测）：
- 列表页 `ul.c_list_bid > li`：<a href title> + <em rel=bxlx>类型</em>
  + 文本「发布时间：<em>2026-07-03 23:06</em> 地域：<em>辽宁</em> 采购人：<em>…</em>」
- 详情页正文容器 `div.vF_detail_content`，服务端渲染，纯 httpx 可采。
"""

import re
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.crawler.base import RawAnnouncement, SourceAdapter, register

DEFAULT_CHANNELS = [
    "https://www.ccgp.gov.cn/cggg/zygg/",  # 中央公告
    "https://www.ccgp.gov.cn/cggg/dfgg/",  # 地方公告
]

_META_RE = re.compile(
    r"发布时间：\s*(?P<time>\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)"
    r"(?:.*?地域：\s*(?P<region>\S+))?"
    r"(?:.*?采购人：\s*(?P<buyer>.+?))?\s*$",
    re.S,
)


@register
class CcgpAdapter(SourceAdapter):
    name = "ccgp"
    display_name = "中国政府采购网"

    @staticmethod
    def parse_list(html: str, base_url: str) -> list[RawAnnouncement]:
        soup = BeautifulSoup(html, "lxml")
        items: list[RawAnnouncement] = []
        for li in soup.select("ul.c_list_bid li"):
            a = li.find("a", href=True)
            if a is None:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            ann_type_el = li.find("em", attrs={"rel": "bxlx"})
            ann_type = ann_type_el.get_text(strip=True) if ann_type_el else None

            publish_time = region = buyer = None
            m = _META_RE.search(li.get_text(" ", strip=True))
            if m:
                raw_time = m.group("time")
                fmt = "%Y-%m-%d %H:%M" if " " in raw_time else "%Y-%m-%d"
                publish_time = datetime.strptime(raw_time, fmt)
                region = m.group("region")
                buyer = m.group("buyer").strip() if m.group("buyer") else None

            items.append(
                RawAnnouncement(
                    url=urljoin(base_url, a["href"]),
                    title=title,
                    publish_time=publish_time,
                    ann_type=ann_type,
                    region=region,
                    buyer=buyer,
                )
            )
        return items

    def list_announcements(self, since: datetime | None = None) -> Iterator[RawAnnouncement]:
        channels = self.config.get("channels", DEFAULT_CHANNELS)
        for channel in channels:
            resp = self.get(channel)
            for item in self.parse_list(resp.text, channel):
                if since and item.publish_time and item.publish_time <= since:
                    break  # 列表新→旧排列，遇到旧条目即停止本频道
                yield item

    def fetch_detail(self, url: str) -> str:
        return self.get(url).text

    def content_selectors(self) -> list[str]:
        return ["div.vF_detail_content", "div.vF_deail_maincontent"]
