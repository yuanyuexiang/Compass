"""企业能力画像维护：结构化数据 → 画像摘要文本 + 语料切块（+向量）。"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai import embeddings
from app.models import CompanyProfile, ProfileChunk

PROFILE_LIST_FIELDS = [
    ("products", "主营产品"),
    ("services", "服务能力"),
    ("industries", "覆盖行业"),
    ("regions", "覆盖区域"),
    ("certifications", "资质证书"),
    ("brands", "合作品牌"),
]


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
