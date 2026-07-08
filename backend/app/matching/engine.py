"""匹配引擎：三级漏斗（tech-design.md §5.2）。

1. 规则硬过滤（零成本）：区域、预算下限、排除大类 —— 来自画像 data.filter；
2. 向量粗排（低成本）：项目向量 × 画像语料向量，无 embedding 时自动跳过；
3. LLM 精排（DeepSeek）：评分卡 + 六项风险 + 参与建议。
"""

import json
import logging
import re

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_config import extract_completion
from app.ai.prompts.match_v1 import MATCH_SYSTEM_PROMPT_V1
from app.matching.schemas import MatchScoreCard
from app.models import Announcement, CompanyProfile, MatchResult, ProfileChunk, Project
from app.opportunity import is_biddable

logger = logging.getLogger(__name__)

STAR_BY_SCORE = ((90, 5), (80, 4), (65, 3), (50, 2), (0, 1))
VECTOR_SIM_THRESHOLD = 0.35
MAX_ATTEMPTS = 3

_WAN_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*万")
_YUAN_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*元")


def parse_budget_yuan(value: str | None) -> float | None:
    """'265.000000万元（人民币）' → 2650000.0；'4604800.45元' → 4604800.45。"""
    if not value:
        return None
    if m := _WAN_RE.search(value):
        return float(m.group(1).replace(",", "")) * 10_000
    if m := _YUAN_RE.search(value):
        return float(m.group(1).replace(",", ""))
    return None


def rule_filter(project: Project, profile_data: dict) -> tuple[bool, str]:
    """返回 (是否通过, 淘汰原因)。画像 data.filter: {regions, min_budget, exclude_mains}。"""
    flt = profile_data.get("filter") or {}
    fields = project.fields or {}

    if regions := flt.get("regions"):
        region = (fields.get("region") or {}).get("value") or ""
        province = region.split("/")[0]
        if province and province not in regions and "全国" not in regions:
            return False, f"区域不符: {region}"

    if (min_budget := flt.get("min_budget")) is not None:
        budget = parse_budget_yuan((fields.get("budget") or {}).get("value"))
        if budget is not None and budget < float(min_budget):
            return False, f"预算低于下限: {budget:.0f}元"

    if excludes := flt.get("exclude_mains"):
        main = (project.category or {}).get("main")
        if main in excludes:
            return False, f"排除大类: {main}"

    return True, ""


def vector_recall(session: Session, project: Project, tenant_id: int) -> bool:
    """向量粗排：项目向量与租户画像语料的最大余弦相似度达到阈值。无向量数据时直接放行。"""
    if project.embedding is None:
        return True
    has_chunks = session.scalar(
        select(ProfileChunk.id)
        .where(ProfileChunk.tenant_id == tenant_id, ProfileChunk.embedding.isnot(None))
        .limit(1)
    )
    if not has_chunks:
        return True
    max_sim = session.scalar(
        select(1 - ProfileChunk.embedding.cosine_distance(project.embedding))
        .where(ProfileChunk.tenant_id == tenant_id, ProfileChunk.embedding.isnot(None))
        .order_by(ProfileChunk.embedding.cosine_distance(project.embedding))
        .limit(1)
    )
    return max_sim is not None and max_sim >= VECTOR_SIM_THRESHOLD


def build_match_input(project: Project, ann: Announcement, profile: CompanyProfile) -> str:
    fields = {k: (v or {}).get("value") for k, v in (project.fields or {}).items()}
    return "\n".join(
        [
            "【企业能力画像】",
            profile.summary_text or json.dumps(profile.data, ensure_ascii=False),
            "",
            "【招标项目】",
            f"标题: {ann.title}",
            f"结构化信息: {json.dumps(fields, ensure_ascii=False)}",
            f"分类: {json.dumps(project.category, ensure_ascii=False)}",
            f"摘要: {project.summary}",
        ]
    )


def llm_rerank(input_text: str) -> MatchScoreCard:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = extract_completion(
                messages=[
                    {"role": "system", "content": MATCH_SYSTEM_PROMPT_V1},
                    {"role": "user", "content": input_text},
                ],
                temperature=0.0,
            )
            content = resp.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("LLM 返回空 content")
            return MatchScoreCard.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.warning("精排失败（第 %d/%d 次）: %s", attempt, MAX_ATTEMPTS, exc)
    raise RuntimeError(f"连续 {MAX_ATTEMPTS} 次精排失败: {last_error}")


def run_match(session: Session, project_id: int, tenant_id: int) -> MatchResult | None:
    """对单个项目 × 单个租户执行三级漏斗，返回 MatchResult（被过滤时返回 None）。幂等。"""
    existing = session.scalar(
        select(MatchResult).where(
            MatchResult.tenant_id == tenant_id, MatchResult.project_id == project_id
        )
    )
    if existing:
        return existing

    project = session.get(Project, project_id)
    profile = session.scalar(select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id))
    if project is None or profile is None:
        return None
    ann = session.get(Announcement, project.announcement_id)

    # 类型闸门：中标/成交/废标类公告不是可投标商机，不匹配推荐（见 app/opportunity.py）
    if not is_biddable(ann.ann_type, ann.title):
        logger.info("非可投标公告，跳过匹配 project=%s [%s]", project_id, ann.ann_type)
        return None

    passed, reason = rule_filter(project, profile.data or {})
    if not passed:
        logger.info("规则过滤 tenant=%s project=%s: %s", tenant_id, project_id, reason)
        return None
    if not vector_recall(session, project, tenant_id):
        logger.info("向量粗排未召回 tenant=%s project=%s", tenant_id, project_id)
        return None

    card = llm_rerank(build_match_input(project, ann, profile))
    result = MatchResult(
        tenant_id=tenant_id,
        project_id=project_id,
        match_score=card.match_score,
        star=card.star,
        advice=card.advice,
        reasons=[r.model_dump() for r in card.reasons],
        risks={k: v.model_dump() for k, v in card.risks.items()},
    )
    session.add(result)
    session.flush()
    return result
