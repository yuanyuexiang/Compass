"""AI 企业画像：企业名 → 秘塔联网搜索 → LLM 整理成画像草稿。

草稿只预填、不落库；filter（仅关注地区/最低预算）属经营决策，交给用户手填，此处不产出。
"""

import json
import logging

from app.ai import websearch
from app.ai.llm_config import extract_completion
from app.ai.prompts.profile_suggest_v1 import PROFILE_SUGGEST_PROMPT_V1

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


def suggest_profile(name: str) -> dict:
    """返回 {draft, sources, confidence, note}；draft 结构对齐画像描述字段。"""
    results = websearch.search(f"{name} 主营业务 产品 服务 资质 案例", size=8)
    if not results:
        return {
            "draft": {"name": name},
            "sources": [],
            "confidence": "low",
            "note": "未搜到公开信息，请手动完善画像",
        }
    context = "\n\n".join(
        f"[来源{i + 1}] {r.get('title') or ''}（{r.get('link') or ''}）\n{r.get('snippet') or ''}"
        for i, r in enumerate(results)
    )
    resp = extract_completion(
        messages=[
            {"role": "system", "content": PROFILE_SUGGEST_PROMPT_V1},
            {"role": "user", "content": f"企业名称：{name}\n\n搜索结果：\n{context}"},
        ],
        temperature=0.1,
    )
    return _parse(resp.choices[0].message.content, name, results)


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
        "sources": obj.get("_sources") or [r["link"] for r in results if r.get("link")][:5],
        "confidence": obj.get("_confidence") or "medium",
        "note": obj.get("_note") or "AI 依据公开网页整理，请核对资质与案例后再保存",
    }
