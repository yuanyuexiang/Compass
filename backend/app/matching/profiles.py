"""企业能力画像维护：结构化数据 → 画像摘要文本 + 语料切块（+向量）。"""

from sqlalchemy import ColumnElement, delete, or_, select
from sqlalchemy.orm import Session

from app.ai import embeddings
from app.models import Announcement, CompanyProfile, ProfileChunk, Project

PROFILE_LIST_FIELDS = [
    ("products", "主营产品"),
    ("services", "服务能力"),
    ("industries", "覆盖行业"),
    ("regions", "覆盖区域"),
    ("certifications", "资质证书"),
    ("brands", "合作品牌"),
]


def get_filter_regions(session: Session, tenant_id: int) -> list[str]:
    """读取画像「仅关注地区」列表（data.filter.regions）；无画像或未设置返回 []。

    与 matching/engine.rule_filter 同源——让商机查询按画像地区过滤，保证查询与推荐口径一致。
    """
    profile = session.scalar(select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id))
    if profile is None:
        return []
    return ((profile.data or {}).get("filter") or {}).get("regions") or []


def get_watched_source_ids(session: Session, tenant_id: int) -> list[int]:
    """读取租户「关注的数据源」（Subscription.source_ids）；未设置返回 []（= 不限）。

    与地区口径同理：采集全局共享，查询/推荐/通知按租户订阅的源过滤，保证各链路口径一致。
    """
    from app.models import Subscription

    sub = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    if sub is None:
        return []
    return [int(i) for i in (sub.source_ids or [])]


def tenant_watches_source(source_ids: list[int], source_id: int) -> bool:
    """空列表 = 不限源；否则要求命中。匹配 fan-out 与查询共用此判定。"""
    return not source_ids or source_id in source_ids


def region_filter_clause(regions: list[str]) -> ColumnElement[bool] | None:
    """画像地区列表 → 公告查询的地区过滤条件（引用 Project，故调用方需 outer join Project）。

    去「省/市」后缀做 ilike，同时匹配列表元数据 region 与结构化字段 region（与 NL 搜索一致，
    兼容「江苏省」匹配「江苏/南京」「南京」）。列表为空或含「全国」→ 返回 None（不加地区限制）。
    """
    if not regions or "全国" in regions:
        return None
    clauses: list[ColumnElement[bool]] = []
    for r in regions:
        pattern = f"%{r.rstrip('省市')}%"
        clauses.append(Announcement.region.ilike(pattern))
        clauses.append(Project.fields["region"]["value"].astext.ilike(pattern))
    return or_(*clauses)


def build_summary_text(data: dict) -> str:
    lines = [f"企业名称: {data.get('name', '')}"]
    if desc := data.get("description"):
        lines.append(f"简介: {desc}")
    for key, label in PROFILE_LIST_FIELDS:
        if values := data.get(key):
            lines.append(f"{label}: {'、'.join(values)}")
    if cases := data.get("cases_text"):
        lines.append(f"成功案例: {cases}")
    return "\n".join(lines)


def upsert_profile(session: Session, tenant_id: int, data: dict) -> CompanyProfile:
    """更新画像并重建语料切块；embedding 可用时同步向量化。"""
    profile = session.scalar(select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id))
    if profile is None:
        profile = CompanyProfile(tenant_id=tenant_id)
        session.add(profile)
    profile.data = data
    profile.summary_text = build_summary_text(data)

    session.execute(delete(ProfileChunk).where(ProfileChunk.tenant_id == tenant_id))
    chunks = [profile.summary_text]
    if cases := data.get("cases_text"):
        chunks.extend(c.strip() for c in cases.split("\n") if len(c.strip()) > 10)
    vectors = embeddings.embed_texts(chunks) if embeddings.available() else [None] * len(chunks)
    for text, vec in zip(chunks, vectors, strict=True):
        session.add(ProfileChunk(tenant_id=tenant_id, text=text, embedding=vec))
    session.flush()
    return profile
