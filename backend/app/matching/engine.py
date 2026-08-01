"""匹配引擎：三级漏斗（tech-design.md §5.2）。

1. 规则硬过滤（零成本）：区域、预算下限、排除大类 —— 来自画像 data.filter；
2. 向量软信号（低成本）：记录项目与画像的相似度，用于观测和候选优先级，不硬淘汰；
3. LLM 分维度判断（DeepSeek）：代码确定性汇总评分、封顶、建议与六项风险。
"""

import json
import logging
import re
from collections.abc import Callable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_config import extract_completion
from app.ai.prompts.match_v3 import MATCH_SYSTEM_PROMPT_V3
from app.core.kv import DEFAULT_QUOTA_MATCH, KEY_QUOTA_MATCH, get_setting
from app.core.ratelimit import try_consume_quota
from app.matching.profiles import region_stem
from app.matching.schemas import DIMENSION_LIMITS, MatchAssessment, MatchScoreCard
from app.models import Announcement, CompanyProfile, MatchResult, ProfileChunk, Project
from app.opportunity import is_biddable

logger = logging.getLogger(__name__)

STAR_BY_SCORE = ((90, 5), (80, 4), (65, 3), (50, 2), (0, 1))
MAX_ATTEMPTS = 3
MATCH_MAX_TOKENS = 1100
PROFILE_SUMMARY_LIMIT = 2000
PROJECT_SUMMARY_LIMIT = 800

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


def vector_similarity(session: Session, project: Project, tenant_id: int) -> float | None:
    """返回项目与画像语料的最大余弦相似度。

    相似度只用于观测和候选优先级，不再硬淘汰商机。当前黄金集没有覆盖向量召回层，
    在召回率得到验证前用固定阈值过滤会静默漏掉真正值得跟进的项目。
    """
    if project.embedding is None:
        return None
    has_chunks = session.scalar(
        select(ProfileChunk.id)
        .where(ProfileChunk.tenant_id == tenant_id, ProfileChunk.embedding.isnot(None))
        .limit(1)
    )
    if not has_chunks:
        return None
    max_sim = session.scalar(
        select(1 - ProfileChunk.embedding.cosine_distance(project.embedding))
        .where(ProfileChunk.tenant_id == tenant_id, ProfileChunk.embedding.isnot(None))
        .order_by(ProfileChunk.embedding.cosine_distance(project.embedding))
        .limit(1)
    )
    return float(max_sim) if max_sim is not None else None


# 按业务相关性抽取公告片段，避免只截正文开头而漏掉后部的资格、技术和评分条款。
CLEAN_TEXT_EXCERPT = 2500
_SECTION_KEYWORDS = {
    "采购需求": 8,
    "项目需求": 8,
    "技术要求": 8,
    "技术参数": 8,
    "采购清单": 8,
    "资格要求": 10,
    "资质": 7,
    "业绩": 7,
    "评分": 7,
    "评审": 6,
    "品牌": 7,
    "预算": 5,
    "最高限价": 5,
    "合同履行": 5,
    "服务范围": 7,
    "建设内容": 7,
    "联合体": 6,
}


def select_relevant_excerpt(text: str | None, max_chars: int = CLEAN_TEXT_EXCERPT) -> str:
    """选择开头概况及命中关键业务条款的段落，并带一行上下文。"""
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text[:max_chars]

    selected: set[int] = set(range(min(8, len(lines))))
    ranked: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        score = sum(weight for keyword, weight in _SECTION_KEYWORDS.items() if keyword in line)
        if score:
            ranked.append((score, idx))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    for _, idx in ranked:
        selected.update(range(max(0, idx - 1), min(len(lines), idx + 3)))

    output: list[str] = []
    size = 0
    for idx in sorted(selected):
        line = lines[idx]
        if size + len(line) + 1 > max_chars:
            continue
        output.append(line)
        size += len(line) + 1
    return "\n".join(output)


def build_match_input(
    project: Project,
    ann: Announcement,
    profile: CompanyProfile,
    similarity: float | None = None,
) -> str:
    fields = {k: (v or {}).get("value") for k, v in (project.fields or {}).items()}
    flt = (profile.data or {}).get("filter") or {}
    regions = "、".join(flt.get("regions") or []) or "不限"
    min_budget = flt.get("min_budget")
    budget_line = f"{min_budget / 10000:g} 万元" if min_budget else "不限"
    profile_summary = profile.summary_text or json.dumps(profile.data, ensure_ascii=False)
    lines = [
        "【企业能力画像】",
        profile_summary[:PROFILE_SUMMARY_LIMIT],
        f"企业硬性筛选条件：关注地区：{regions}；最低预算线：{budget_line}",
        "",
        "【招标项目】",
        f"标题: {ann.title}",
        f"结构化信息: {json.dumps(fields, ensure_ascii=False)}",
        f"分类: {json.dumps(project.category, ensure_ascii=False)}",
        f"摘要: {(project.summary or '')[:PROJECT_SUMMARY_LIMIT]}",
    ]
    if similarity is not None:
        lines.append(f"语义相似度（仅供参考，不是淘汰条件）: {similarity:.3f}")
    if excerpt := select_relevant_excerpt(getattr(ann, "clean_text", None)):
        lines.append(f"公告原文（相关段落）: {excerpt}")
    return "\n".join(lines)


def star_from_score(score: float) -> int:
    for threshold, star in STAR_BY_SCORE:
        if score >= threshold:
            return star
    return 1


def finalize_assessment(
    assessment: MatchAssessment, similarity: float | None = None
) -> MatchScoreCard:
    """按固定权重汇总评分并应用业务封顶，消除模型心算和口径漂移。"""
    dimensions = assessment.dimensions
    missing = set(DIMENSION_LIMITS) - set(dimensions)
    if missing:
        raise ValueError(f"评分维度缺失: {', '.join(sorted(missing))}")

    score = sum(
        min(float(dimensions[key].score), limit) for key, limit in DIMENSION_LIMITS.items()
    )
    caps = {
        "none": 34,
        "partial": 49,
        "medium": 79,
        "high": 100,
    }
    score = min(score, caps[assessment.fit_level])
    if assessment.delivery_mode == "partner":
        score = min(score, 79)
    elif assessment.delivery_mode == "unsuitable":
        score = min(score, 49)
    if assessment.qualification_status == "missing":
        score = min(score, 49)

    score = round(score, 1)
    if score >= 80 and assessment.delivery_mode == "independent":
        advice = "建议参与"
    elif score >= 65:
        advice = "谨慎参与"
    else:
        advice = "不建议参与"
    return MatchScoreCard(
        match_score=score,
        star=star_from_score(score),
        advice=advice,
        reasons=assessment.reasons,
        risks=assessment.risks,
        dimensions=dimensions,
        fit_level=assessment.fit_level,
        qualification_status=assessment.qualification_status,
        delivery_mode=assessment.delivery_mode,
        vector_similarity=similarity,
    )


def llm_rerank(
    input_text: str,
    tenant_id: int | None = None,
    system_prompt: str | None = None,
    similarity: float | None = None,
    scene: str = "match",
    usage_callback: Callable[[object], None] | None = None,
) -> MatchScoreCard:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = extract_completion(
                messages=[
                    {"role": "system", "content": system_prompt or MATCH_SYSTEM_PROMPT_V3},
                    {"role": "user", "content": input_text},
                ],
                temperature=0.0,
                max_tokens=MATCH_MAX_TOKENS,
                scene=scene,
                tenant_id=tenant_id,
            )
            if usage_callback is not None:
                usage_callback(getattr(resp, "usage", None))
            content = resp.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("LLM 返回空 content")
            # 容忍模型偶尔加 ```json 围栏或前后说明，但只解析首尾 JSON 对象。
            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("LLM 返回内容中没有 JSON 对象")
            assessment = MatchAssessment.model_validate(json.loads(content[start : end + 1]))
            return finalize_assessment(assessment, similarity)
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
    similarity = vector_similarity(session, project, tenant_id)

    # 每日精排配额（成本护栏）：超额跳过，公告仍可检索，只是当天不再产生新推荐
    quota = int(get_setting(session, KEY_QUOTA_MATCH, DEFAULT_QUOTA_MATCH))
    if not try_consume_quota(tenant_id, "match", quota):
        logger.warning(
            "租户 %s 当日精排配额（%d）已用完，跳过 project=%s", tenant_id, quota, project_id
        )
        return None

    card = llm_rerank(
        build_match_input(project, ann, profile, similarity),
        tenant_id,
        similarity=similarity,
    )
    if existing is not None:
        # 重评估：更新评分与结论，保留 follow_status（用户的跟进标记不可被冲掉）
        existing.match_score = card.match_score
        existing.star = card.star
        existing.advice = card.advice
        existing.reasons = [r.model_dump() for r in card.reasons]
        existing.risks = {k: v.model_dump() for k, v in card.risks.items()}
        existing.score_details = {
            "dimensions": {k: v.model_dump() for k, v in card.dimensions.items()},
            "fit_level": card.fit_level,
            "qualification_status": card.qualification_status,
            "delivery_mode": card.delivery_mode,
            "vector_similarity": card.vector_similarity,
        }
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
        score_details={
            "dimensions": {k: v.model_dump() for k, v in card.dimensions.items()},
            "fit_level": card.fit_level,
            "qualification_status": card.qualification_status,
            "delivery_mode": card.delivery_mode,
            "vector_similarity": card.vector_similarity,
        },
    )
    session.add(result)
    session.flush()
    return result
