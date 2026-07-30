"""AI 企业画像：四路信源（官网正文/本库中标记录/招聘摘要/综合网页）→ LLM 分节整理成草稿。

- 草稿只预填、不落库；filter（仅关注地区/最低预算）属经营决策，交给用户手填，此处不产出。
- 任何一路信源失败只跳过该路，不阻塞整体；置信度按信源覆盖度评定（代码判定，非 LLM 自评）。
- 本库中标检索复用「可投标闸门」保留入库的结果类公告——中过的标就是实锤能力，
  这条路也是 V3 竞争对手分析的种子。
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import or_, select

from app.ai import websearch
from app.ai.llm_config import extract_completion
from app.ai.prompts.profile_suggest_v2 import PROFILE_SUGGEST_PROMPT_V2
from app.core.config import settings

logger = logging.getLogger(__name__)

# 只整理描述性字段，对齐画像 EMPTY_PROFILE；filter 不由 AI 产出
DRAFT_FIELDS = (
    "name",
    "description",
    "products",
    "services",
    "industries",
    "regions",
    "certifications",
    "brands",
    "cases_text",
)

SITE_TEXT_LIMIT = 2500
BID_SNIPPET_RADIUS = 120


def bid_snippet(text: str | None, name: str) -> str:
    """公告正文里截取企业名前后各 BID_SNIPPET_RADIUS 字，作为中标证据片段。"""
    if not text:
        return ""
    idx = text.find(name)
    if idx < 0:
        return text[: BID_SNIPPET_RADIUS * 2]
    start = max(0, idx - BID_SNIPPET_RADIUS)
    return text[start : idx + len(name) + BID_SNIPPET_RADIUS].replace("\n", " ")


def confidence_of(site_text: str | None, bids: list, web: list) -> str:
    """置信度按信源覆盖度：官网正文+中标记录都有→high；有任一信源→medium；全空→low。"""
    if site_text and bids:
        return "high"
    if site_text or bids or web:
        return "medium"
    return "low"


def _search_local_bids(name: str, limit: int = 6) -> list[dict]:
    """本平台公告库检索该企业（优先结果类公告=中标实锤）。零成本，随铺源增长越来越强。"""
    from app.core.db import session_scope
    from app.models import Announcement

    pattern = f"%{name}%"
    with session_scope() as session:
        rows = session.scalars(
            select(Announcement)
            .where(
                or_(
                    Announcement.title.ilike(pattern),
                    Announcement.clean_text.ilike(pattern),
                )
            )
            .order_by(
                Announcement.biddable.asc().nullslast(),  # 结果类（biddable=False）优先
                Announcement.publish_time.desc().nullslast(),
            )
            .limit(limit)
        ).all()
        return [
            {
                "title": a.title,
                "url": a.url,
                "region": a.region,
                "publish_time": a.publish_time.strftime("%Y-%m") if a.publish_time else "",
                "snippet": bid_snippet(a.clean_text, name),
                "is_result": a.biddable is False,
            }
            for a in rows
        ]


def _pick_official_site(name: str, results: list[dict]) -> str | None:
    """从「官网」搜索结果里让 LLM 挑出真正属于该企业的官网链接（防同名企业张冠李戴）。"""
    if not results:
        return None
    listing = "\n".join(
        f"{i + 1}. {r.get('title') or ''} | {r.get('link') or ''} | {r.get('snippet') or ''}"
        for i, r in enumerate(results[:5])
    )
    try:
        resp = extract_completion(
            messages=[
                {
                    "role": "system",
                    "content": "从候选链接中找出属于该企业自己的官方网站，输出 json："
                    '{"link": "官网链接或null"}。新闻/招聘/黄页/同名其他企业一律不算。',
                },
                {"role": "user", "content": f"企业名称：{name}\n候选：\n{listing}"},
            ],
            temperature=0.0,
            scene="profile_suggest",
            max_tokens=200,
        )
        obj = json.loads(resp.choices[0].message.content or "{}")
        link = obj.get("link")
        return link if isinstance(link, str) and link.startswith("http") else None
    except Exception:  # noqa: BLE001  官网识别失败只损失一路信源
        logger.warning("官网识别失败（%s）", name, exc_info=True)
        return None


def _fetch_site_text(url: str) -> str | None:
    """抓官网首页正文（动态站 Playwright 兜底），失败返回 None 不阻塞。"""
    import httpx

    from app.parsing.clean import html_to_text

    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": settings.crawler_user_agent},
            timeout=15.0,
            verify=settings.crawler_verify_ssl,
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
        from app.ai.suggest import looks_dynamic

        if looks_dynamic(html):
            from app.crawler import browser

            if browser.available():
                html = browser.render(url)
        text = html_to_text(html)
        return text[:SITE_TEXT_LIMIT] or None
    except Exception:  # noqa: BLE001
        logger.warning("官网抓取失败 %s", url, exc_info=True)
        return None


def _safe_search(query: str, size: int) -> list[dict]:
    try:
        return websearch.search(query, size=size)
    except Exception:  # noqa: BLE001  单路搜索失败不阻塞其他信源
        logger.warning("搜索失败「%s」", query, exc_info=True)
        return []


def _build_context(
    name: str, site_url: str | None, site_text: str | None,
    bids: list[dict], jobs: list[dict], web: list[dict],
) -> str:
    parts = [f"企业名称：{name}"]
    if site_text:
        parts.append(f"【官网正文】（{site_url}）\n{site_text}")
    if bids:
        lines = [
            f"- {'[中标/结果公告] ' if b['is_result'] else ''}{b['title']}"
            f"（{b['region'] or ''} {b['publish_time']}）：{b['snippet']}"
            for b in bids
        ]
        parts.append("【中标记录】（来自本平台公告库）\n" + "\n".join(lines))
    if jobs:
        lines = [f"- {r.get('title') or ''}：{r.get('snippet') or ''}" for r in jobs]
        parts.append("【招聘信息】\n" + "\n".join(lines))
    if web:
        lines = [
            f"- {r.get('title') or ''}（{r.get('link') or ''}）：{r.get('snippet') or ''}"
            for r in web
        ]
        parts.append("【综合网页】\n" + "\n".join(lines))
    return "\n\n".join(parts)


def suggest_profile(name: str, tenant_id: int | None = None) -> dict:
    """返回 {draft, sources, source_groups, confidence, note}；draft 对齐画像描述字段。"""
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_web = pool.submit(_safe_search, f"{name} 主营业务 产品 服务 资质 案例", 6)
        f_jobs = pool.submit(_safe_search, f"{name} 招聘 岗位", 5)
        f_site = pool.submit(_safe_search, f"{name} 官网", 5)
        f_bids = pool.submit(_search_local_bids, name)
        web, jobs, site_results, bids = (
            f_web.result(), f_jobs.result(), f_site.result(), f_bids.result(),
        )

    site_url = _pick_official_site(name, site_results)
    site_text = _fetch_site_text(site_url) if site_url else None

    if not (site_text or bids or jobs or web):
        return {
            "draft": {"name": name},
            "sources": [],
            "source_groups": [],
            "confidence": "low",
            "note": "未搜到公开信息，请手动完善画像",
        }

    resp = extract_completion(
        messages=[
            {"role": "system", "content": PROFILE_SUGGEST_PROMPT_V2},
            {
                "role": "user",
                "content": _build_context(name, site_url, site_text, bids, jobs, web),
            },
        ],
        temperature=0.1,
        scene="profile_suggest",
        tenant_id=tenant_id,
    )
    result = _parse(resp.choices[0].message.content, name, web)
    # 解析失败（草稿只剩企业名）保持 low；解析成功才按信源覆盖度评级
    if len(result["draft"]) > 1:
        result["confidence"] = confidence_of(site_text, bids, web)
    groups = []
    if site_url:
        groups.append({"label": "官网", "items": [{"title": site_url, "link": site_url}]})
    if bids:
        groups.append({
            "label": "中标记录（本平台库）",
            "items": [{"title": b["title"], "link": b["url"]} for b in bids[:4]],
        })
    if jobs:
        groups.append({
            "label": "招聘",
            "items": [
                {"title": r.get("title") or r.get("link"), "link": r.get("link")}
                for r in jobs[:3] if r.get("link")
            ],
        })
    if web:
        groups.append({
            "label": "网页",
            "items": [
                {"title": r.get("title") or r.get("link"), "link": r.get("link")}
                for r in web[:4] if r.get("link")
            ],
        })
    result["source_groups"] = groups
    return result


def _parse(content: str, name: str, results: list[dict]) -> dict:
    """宽容解析 LLM 输出（可能带 ```json 围栏或前后杂字）。失败则退化为仅企业名草稿。"""
    obj = None
    start, end = content.find("{"), content.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(content[start : end + 1])
        except json.JSONDecodeError as exc:
            logger.warning("画像草稿 JSON 解析失败：%s", exc)
    if not isinstance(obj, dict):
        return {
            "draft": {"name": name},
            "sources": [r["link"] for r in results if r.get("link")][:5],
            "confidence": "low",
            "note": "AI 解析失败，请根据来源手动填写",
        }
    draft = {k: obj[k] for k in DRAFT_FIELDS if obj.get(k) not in (None, "", [])}
    draft.setdefault("name", name)
    return {
        "draft": draft,
        "sources": [r["link"] for r in results if r.get("link")][:5],
        "confidence": "medium",
        "note": obj.get("_note") or "AI 依据多路公开信源整理，请核对资质与案例后再保存",
    }
