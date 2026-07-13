"""AI 自动适配（V1.5 前置能力）：LLM 分析页面 HTML，自动生成 generic 适配器的选择器配置。"""

import json
import logging
import re

from bs4 import BeautifulSoup, Comment

from app.ai.llm_config import extract_completion
from app.ai.prompts.suggest_selectors_v1 import (
    SUGGEST_CONTENT_PROMPT_V1,
    SUGGEST_LIST_PROMPT_V1,
)

logger = logging.getLogger(__name__)

MAX_HTML_CHARS = 18_000
MAX_ATTEMPTS = 2
MIN_VISIBLE_TEXT = 500  # 可见文本低于此值疑似 JS 壳

KEEP_ATTRS = ("class", "id", "href", "title")
# 混淆脚本特征（瑞数等 JS 挑战反爬常见变量名 _0x1a2b…）
_OBFUSCATION_RE = re.compile(r"_0x[0-9a-f]{4,}")


def looks_dynamic(html: str) -> bool:
    """页面疑似 JS 动态渲染 / 反爬：可见文本极少，或含混淆脚本特征。

    用于 smart-suggest 判定该走 httpx（静态）还是 Playwright（动态）路线。
    """
    if len(_OBFUSCATION_RE.findall(html)) >= 3:
        return True
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    node = soup.body or soup
    visible = node.get_text(" ", strip=True) if node else ""
    return len(visible) < MIN_VISIBLE_TEXT


def suggest_config_and_items(list_html: str, base_url: str):
    """给一段列表页 HTML → LLM 生成选择器 → 解析出条目，返回 (config, items)。

    smart-suggest 与旧 suggest 端点共用：静态路线传 httpx 的 HTML，动态路线传渲染后的 HTML。
    低于 3 条时带反馈重试一次。
    """
    from app.crawler.adapters.generic import GenericAdapter

    selectors = suggest_list_selectors(list_html)
    config = {"list_url": base_url, **selectors}
    items = GenericAdapter.parse_list(list_html, base_url, config) if selectors else []
    if len(items) < 3:
        fb = f"item_selector「{config.get('item_selector')}」只匹配到 {len(items)} 条公告"
        retry = suggest_list_selectors(list_html, feedback=fb)
        if retry:
            retry_config = {"list_url": base_url, **retry}
            retry_items = GenericAdapter.parse_list(list_html, base_url, retry_config)
            if len(retry_items) > len(items):
                config, items = retry_config, retry_items
    return config, items


def compact_html(html: str, max_chars: int = MAX_HTML_CHARS) -> str:
    """精简 HTML 供 LLM 分析：去脚本样式与无关属性，保留结构与 class/id。"""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "link", "meta", "img"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for el in soup.find_all(True):
        el.attrs = {k: v for k, v in el.attrs.items() if k in KEEP_ATTRS}
    body = soup.body or soup
    return str(body)[:max_chars]


def _llm_json(system_prompt: str, user_content: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = extract_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
            )
            content = resp.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("LLM 返回空 content")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("非 json 对象")
            return data
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("选择器识别失败（第 %d/%d 次）: %s", attempt, MAX_ATTEMPTS, exc)
    raise RuntimeError(f"选择器识别失败: {last_error}")


def suggest_list_selectors(list_html: str, feedback: str | None = None) -> dict:
    """→ {item_selector, link_selector, date_selector}（值可能为 None）。"""
    user = compact_html(list_html)
    if feedback:
        user = f"{user}\n\n【上次尝试的反馈】{feedback}，请重新分析并给出不同的选择器。"
    data = _llm_json(SUGGEST_LIST_PROMPT_V1, user)
    result = {}
    for key in ("item_selector", "link_selector", "date_selector"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


def suggest_content_selector(detail_html: str) -> str | None:
    data = _llm_json(SUGGEST_CONTENT_PROMPT_V1, compact_html(detail_html))
    value = data.get("content_selector")
    return value.strip() if isinstance(value, str) and value.strip() else None
