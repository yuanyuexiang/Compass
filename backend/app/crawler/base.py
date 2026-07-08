"""源适配器框架（tech-design.md §4.1）。

新增平台 = 新增一个 Adapter 子类并用 @register 注册，不动框架代码。
适配器只负责「列出公告 + 抓取详情 HTML + 发现附件链接」，清洗/解析/入库由流水线统一处理。
"""

import hashlib
import posixpath
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings

ATTACHMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")


@dataclass(slots=True)
class RawAnnouncement:
    url: str
    title: str
    publish_time: datetime | None = None
    ann_type: str | None = None
    region: str | None = None
    buyer: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(slots=True)
class AttachmentLink:
    url: str
    filename: str


def url_fingerprint(url: str) -> str:
    """URL 归一化指纹，用于去重（DB 唯一约束兜底）。"""
    normalized = url.strip().rstrip("/").split("#")[0]
    return hashlib.sha256(normalized.encode()).hexdigest()


class SourceAdapter(ABC):
    """平台适配器基类：内置限速（§10.4 合规）与统一 HTTP 客户端。"""

    name: str  # 注册名，与 sources.adapter 对应
    display_name: str = ""  # 平台中文名（界面展示用），子类必须设置

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.min_interval = float(
            self.config.get("min_interval_seconds", settings.crawler_min_interval_seconds)
        )
        self._client: httpx.Client | None = None
        self._last_request_at = 0.0

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": settings.crawler_user_agent},
                timeout=settings.crawler_timeout_seconds,
                follow_redirects=True,
                verify=settings.crawler_verify_ssl,
            )
        return self._client

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str) -> httpx.Response:
        """限速 GET：两次请求间强制 min_interval 间隔。"""
        self._throttle()
        resp = self.client.get(url)
        self._last_request_at = time.monotonic()
        resp.raise_for_status()
        return resp

    def post_json(self, url: str, payload: dict) -> httpx.Response:
        """限速 POST（JSON body），用于接口型源站。"""
        self._throttle()
        resp = self.client.post(url, json=payload)
        self._last_request_at = time.monotonic()
        resp.raise_for_status()
        return resp

    def render(self, url: str, wait_selector: str | None = None) -> str:
        """浏览器渲染取 HTML（JS 动态站用，tech-design §4.1）。限速独立于 httpx。"""
        from app.crawler import browser

        browser.throttle(
            float(self.config.get("min_interval_seconds", settings.browser_min_interval_seconds))
        )
        return browser.render(url, wait_selector=wait_selector)

    @abstractmethod
    def list_announcements(self, since: datetime | None = None) -> Iterator[RawAnnouncement]:
        """列出公告（新→旧）。since 之前的条目应停止产出。"""

    @abstractmethod
    def fetch_detail(self, url: str) -> str:
        """抓取公告详情页，返回原始 HTML。"""

    def content_selectors(self) -> list[str]:
        """详情页正文 CSS 选择器（供清洗模块使用），子类按站点覆盖。"""
        return []

    def extract_attachments(self, html: str, base_url: str) -> list[AttachmentLink]:
        """从详情页发现附件链接。默认按扩展名扫描全部 <a>，子类可覆盖。"""
        soup = BeautifulSoup(html, "lxml")
        links: list[AttachmentLink] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            path = urlparse(href).path.lower()
            if not path.endswith(ATTACHMENT_EXTENSIONS):
                continue
            url = urljoin(base_url, href).split("#")[0]  # 附件不含锚点，去掉以免重复
            if url in seen:
                continue
            seen.add(url)
            filename = a.get_text(strip=True) or unquote(posixpath.basename(urlparse(url).path))
            links.append(AttachmentLink(url=url, filename=filename))
        return links

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


ADAPTERS: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    ADAPTERS[cls.name] = cls
    return cls


def get_adapter(name: str, config: dict | None = None) -> SourceAdapter:
    import app.crawler.adapters  # noqa: F401  触发适配器注册

    if name not in ADAPTERS:
        raise KeyError(f"未注册的适配器: {name}（已注册: {sorted(ADAPTERS)}）")
    return ADAPTERS[name](config)
