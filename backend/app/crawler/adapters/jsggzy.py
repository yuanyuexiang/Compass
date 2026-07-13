"""江苏省公共资源交易平台（jsggzy.jszwfw.gov.cn）适配器。

Epoint 框架站点（2026-07 实测）：
- 列表数据：POST /inteligentsearch/rest/esinteligentsearch/getFullTextDataNew（JSON），
  按 categorynum 前缀过滤、infodatepx 降序；record.linkurl 为详情页相对路径。
- 详情页服务端渲染，正文容器 div.ewb-trade-con。
- 分类映射见 /js/xxtypelist.json；默认采七个板块的「招标/采购公告」类目。

反爬（2026-07 生产实测）：站点已上瑞数类 JS 挑战——裸 httpx 拿到的是挑战页 HTML 而非
JSON。故默认走浏览器模式（use_browser，默认 True）：真浏览器先导航列表页执行挑战脚本
拿通行 cookie，再在同一上下文里 fetch 数据接口。若将来反爬撤除，config 设 use_browser=false
可回退纯 httpx（更快）。
"""

import logging
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import urljoin

from app.crawler.base import RawAnnouncement, SourceAdapter, register

logger = logging.getLogger(__name__)

BASE_URL = "https://jsggzy.jszwfw.gov.cn"
SEARCH_API = f"{BASE_URL}/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
# 浏览器模式先导航此页过瑞数挑战（拿到域 cookie 后同域 fetch 接口即放行）
NAV_PAGE = f"{BASE_URL}/jyxx/tradeInfonew.html"

# 各板块「招标/采购公告」类目（来自 /js/xxtypelist.json，2026-07 核对）
DEFAULT_CATEGORYNUMS = {
    "003001001": "建设工程",
    "003002001": "交通工程",
    "003003001": "水利工程",
    "003004002": "政府采购",
    "003009001": "其他交易",
    "003010001": "药品耗材",
    "003011001": "机电设备",
}


def _search_payload(categorynum: str, rows: int) -> dict:
    return {
        "token": "",
        "pn": 0,
        "rn": rows,
        "sdt": "",
        "edt": "",
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "title",
        "cnum": "001",
        "sort": '{"infodatepx":"0"}',  # 按发布时间降序
        "ssort": "title",
        "cl": 200,
        "condition": [
            {"fieldName": "categorynum", "isLike": True, "likeType": 2, "equal": categorynum}
        ],
        "time": None,
        "highlights": "title",
        "accuracy": "",
        "noParticiple": "0",
        "searchRange": None,
        "isBusiness": "1",
    }


@register
class JsggzyAdapter(SourceAdapter):
    name = "jsggzy"
    display_name = "江苏省公共资源交易平台"

    @staticmethod
    def parse_records(data: dict) -> list[RawAnnouncement]:
        items: list[RawAnnouncement] = []
        for rec in data.get("result", {}).get("records", []):
            linkurl = rec.get("linkurl")
            title = (rec.get("title") or "").strip()
            if not linkurl or not title:
                continue
            publish_time = None
            if rec.get("infodatepx"):
                publish_time = datetime.strptime(rec["infodatepx"], "%Y-%m-%d %H:%M:%S")
            items.append(
                RawAnnouncement(
                    url=urljoin(BASE_URL, linkurl),
                    title=title,
                    publish_time=publish_time,
                    ann_type=rec.get("categoryname") or None,
                    region=rec.get("zhuanzai") or None,  # 转载来源即地市交易平台
                    buyer=None,  # 列表无采购人字段，M2 由 LLM 从正文提取
                    extra={"infoid": rec.get("infoid"), "categorynum": rec.get("categorynum")},
                )
            )
        return items

    def list_announcements(self, since: datetime | None = None) -> Iterator[RawAnnouncement]:
        categorynums = self.config.get("categorynums", list(DEFAULT_CATEGORYNUMS))
        rows = int(self.config.get("rows_per_category", 20))
        if self.config.get("use_browser", True):
            yield from self._list_via_browser(categorynums, rows, since)
        else:
            yield from self._list_via_httpx(categorynums, rows, since)

    def _list_via_httpx(
        self, categorynums: list[str], rows: int, since: datetime | None
    ) -> Iterator[RawAnnouncement]:
        for categorynum in categorynums:
            resp = self.post_json(SEARCH_API, _search_payload(categorynum, rows))
            for item in self.parse_records(resp.json()):
                if since and item.publish_time and item.publish_time <= since:
                    break  # 已按时间降序，遇旧即停本类目
                yield item

    def _list_via_browser(
        self, categorynums: list[str], rows: int, since: datetime | None
    ) -> Iterator[RawAnnouncement]:
        """浏览器过瑞数挑战后，在同一上下文里逐类目 fetch 数据接口。"""
        from app.crawler import browser

        payloads = [_search_payload(c, rows) for c in categorynums]
        results = browser.fetch_json_via_page(NAV_PAGE, SEARCH_API, payloads)
        for res in results:
            if not res or not res.get("ok"):
                logger.warning("jsggzy 浏览器 fetch 未拿到 JSON: %s", res)
                continue
            for item in self.parse_records(res["json"]):
                if since and item.publish_time and item.publish_time <= since:
                    break
                yield item

    def fetch_detail(self, url: str) -> str:
        # 详情页同受瑞数保护，浏览器模式下用渲染取正文
        if self.config.get("use_browser", True):
            return self.render(url, wait_selector="div.ewb-trade-con")
        return self.get(url).text

    def content_selectors(self) -> list[str]:
        return ["div.ewb-trade-con", "div.con"]
