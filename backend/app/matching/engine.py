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
from app.ai.prompts.match_v2 import MATCH_SYSTEM_PROMPT_V2
from app.core.kv import DEFAULT_QUOTA_MATCH, KEY_QUOTA_MATCH, get_setting
from app.core.ratelimit import try_consume_quota
from app.matching.profiles import region_stem
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
        # 按地名主干比较：「广西」能命中画像里的「广西壮族自治区」（写法差异不误杀）
        if (
            province
            and region_stem(province) not in {region_stem(r) for r in regions}
            and "全国" not in regions
        ):
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


# 公告原文节选长度：风险判定（品牌/资质/排他条款）需要原文细节，但要控 token 成本
CLEAN_TEXT_EXCERPT = 1500


def build_match_input(project: Project, ann: Announcement, profile: CompanyProfile) -> str:
    fields = {k: (v or {}).get("value") for k, v in (project.fields or {}).items()}
    flt = (profile.data or {}).get("filter") or {}
    regions = "、".join(flt.get("regions") or []) or "不限"
    min_budget = flt.get("min_budget")
    budget_line = f"{min_budget / 10000:g} 万元" if min_budget else "不限"
    lines = [
        "【企业能力画像】",
        profile.summary_text or json.dumps(profile.data, ensure_ascii=False),
        f"企业硬性筛选条件：关注地区：{regions}；最低预算线：{budget_line}",
        "",
        "【招标项目】",
        f"标题: {ann.title}",
        f"结构化信息: {json.dumps(fields, ensure_ascii=False)}",
        f"分类: {json.dumps(project.category, ensure_ascii=False)}",
        f"摘要: {project.summary}",
    ]
    # 原文节选：风险 evidence 的唯一可靠来源（v1 只给摘要，模型只能编证据）
    if clean_text := getattr(ann, "clean_text", None):
        lines.append(f"公告原文（节选）: {clean_text[:CLEAN_TEXT_EXCERPT]}")
    return "\n".join(lines)


def star_from_score(score: float) -> int:
    for threshold, star in STAR_BY_SCORE:
        if score >= threshold:
            return star
    return 1


def llm_rerank(
    input_text: str, tenant_id: int | None = None, system_prompt: str | None = None
) -> MatchScoreCard:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = extract_completion(
                messages=[
                    {"role": "system", "content": system_prompt or MATCH_SYSTEM_PROMPT_V2},
                    {"role": "user", "content": input_text},
                ],
                temperature=0.0,
                scene="match",
                tenant_id=tenant_id,
            )
            content = resp.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("LLM 返回空 content")
            card = MatchScoreCard.model_validate_json(content)
            # star 一律由分数映射（v2 起模型不再输出 star，v1 输出的也覆盖，保证口径唯一）
            card.star = star_from_score(card.match_score)
            return card
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.warning("精排失败（第 %d/%d 次）: %s", attempt, MAX_ATTEMPTS, exc)
    raise RuntimeError(f"连续 {MAX_ATTEMPTS} 次精排失败: {last_error}")


def run_match(
    session: Session, project_id: int, tenant_id: int, force: bool = False
) -> MatchResult | None:
    """对单个项目 × 单个租户执行三级漏斗，返回 MatchResult（被过滤时返回 None）。幂等。

    force=True（画像改动后的重评估）：已有结果按新画像重新打分（保留用户跟进状态）；
    新规则把它排除时，未跟进过的旧结果删除、已跟进的保留（不夺走用户正在跟的项目）。
    """
    existing = session.scalar(
        select(MatchResult).where(
            MatchResult.tenant_id == tenant_id, MatchResult.project_id == project_id
        )
    )
    if existing and not force:
        return existing

    def drop_stale() -> None:
        if existing is not None and existing.follow_status == "待看":
            session.delete(existing)
            session.flush()

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
        drop_stale()
        return None
    if not vector_recall(session, project, tenant_id):
        logger.info("向量粗排未召回 tenant=%s project=%s", tenant_id, project_id)
        drop_stale()
        return None

    # 每日精排配额（成本护栏）：超额跳过，公告仍可检索，只是当天不再产生新推荐
    quota = int(get_setting(session, KEY_QUOTA_MATCH, DEFAULT_QUOTA_MATCH))
    if not try_consume_quota(tenant_id, "match", quota):
        logger.warning(
            "租户 %s 当日精排配额（%d）已用完，跳过 project=%s", tenant_id, quota, project_id
        )
        return None

    card = llm_rerank(build_match_input(project, ann, profile), tenant_id)
    if existing is not None:
        # 重评估：更新评分与结论，保留 follow_status（用户的跟进标记不可被冲掉）
        existing.match_score = card.match_score
        existing.star = card.star
        existing.advice = card.advice
        existing.reasons = [r.model_dump() for r in card.reasons]
        existing.risks = {k: v.model_dump() for k, v in card.risks.items()}
        session.flush()
        return existing
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
