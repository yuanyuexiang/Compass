"""秘塔 AI 搜索客户端（AI 企业画像联网检索）。

契约：POST https://metaso.cn/api/v1/search，Bearer 鉴权，
请求 {"q","scope","size"}，返回 {"webpages":[{title,link,snippet,score,date}, ...]}。
未配置 METASO_API_KEY 时 available() 为 False，调用方应优雅降级。
"""

import logging
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

METASO_SEARCH_URL = "https://metaso.cn/api/v1/search"

# 合规红线（tech-design §10.4）：不采商业企业信息聚合平台，命中来源直接丢弃
BLOCKED_DOMAINS = (
    "tianyancha.com",
    "qcc.com",
    "qichacha.com",
    "aiqicha.baidu.com",
    "qixin.com",
    "qixinbao.com",
)


def available() -> bool:
    """是否已配置秘塔 key。"""
    return bool(settings.metaso_api_key)


def _blocked(link: str) -> bool:
    host = (urlparse(link).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


def search(query: str, size: int = 8, scope: str = "webpage") -> list[dict]:
    """联网搜索，返回 [{title, link, snippet, score, date}]（已滤除聚合平台）。

    未配置 key 抛 RuntimeError；接口错误/网络异常向上抛，由路由转成用户可读错误。
    """
    if not available():
        raise RuntimeError("未配置 METASO_API_KEY，无法联网搜索")
    resp = httpx.post(
        METASO_SEARCH_URL,
        headers={"Authorization": f"Bearer {settings.metaso_api_key}"},
        json={"q": query, "scope": scope, "size": str(size)},
        timeout=40.0,
        verify=settings.crawler_verify_ssl,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errCode"):
        raise RuntimeError(f"秘塔搜索错误：{data.get('errMsg')}")
    results: list[dict] = []
    for w in data.get("webpages") or []:
        link = w.get("link") or ""
        if _blocked(link):
            continue
        results.append(
            {
                "title": w.get("title"),
                "link": link,
                "snippet": w.get("snippet"),
                "score": w.get("score"),
                "date": w.get("date"),
            }
        )
    logger.info("秘塔搜索「%s」命中 %d 条（过滤后）", query, len(results))
    return results
