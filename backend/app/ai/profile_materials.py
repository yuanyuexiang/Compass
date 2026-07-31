"""企业上传画像材料 → 原子事实与证据。

第一版聚焦中标通知书/中标公告的结构化项目案例。抽取结果始终是 pending，
只有用户确认后才会进入正式画像。
"""

import json
import re

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.llm_config import extract_completion
from app.ai.prompts.profile_material_award_v1 import PROFILE_MATERIAL_AWARD_PROMPT_V1
from app.models import ProfileEvidence, ProfileFact, ProfileMaterial

MATERIAL_TEXT_LIMIT = 20_000
ACCEPTED_ROLES = {
    "winner",
    "supplier",
    "consortium_member",
    "candidate",
    "mentioned",
    "unknown",
}


class ProjectCaseValue(BaseModel):
    project_name: str = Field(min_length=2, max_length=500)
    company_role: str = "unknown"
    customer: str | None = None
    amount_yuan: float | None = Field(default=None, ge=0)
    region: str | None = None
    awarded_at: str | None = None
    services: list[str] = []

    @field_validator("company_role", mode="before")
    @classmethod
    def normalize_role(cls, value):
        return value if value in ACCEPTED_ROLES else "unknown"

    @field_validator("services", mode="before")
    @classmethod
    def normalize_services(cls, value):
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))[:20]


class ExtractedAwardFact(ProjectCaseValue):
    evidence_quote: str = Field(min_length=2, max_length=500)
    evidence_page: int | None = Field(default=None, ge=1)


class AwardExtraction(BaseModel):
    facts: list[ExtractedAwardFact] = []


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def evidence_is_grounded(quote: str, text: str) -> bool:
    """证据必须能在原文中逐字定位；仅忽略排版空白差异。"""
    return _compact(quote) in _compact(text)


def evidence_page(quote: str, text: str) -> int | None:
    """根据解析器插入的页码标记定位证据页，不信任模型自行填写的页码。"""
    matches = list(re.finditer(r"\[第(\d+)页\]", text))
    for index, marker in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if evidence_is_grounded(quote, text[marker.end() : end]):
            return int(marker.group(1))
    return None


def canonical_case_key(project_name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", project_name).lower()[:256]


def format_case_line(case: ProjectCaseValue) -> str:
    amount = f"{case.amount_yuan / 10_000:g}万元" if case.amount_yuan is not None else ""
    details = "、".join(case.services)
    suffix = "，".join(part for part in (amount, details) if part)
    return f"{case.project_name}{f'（{suffix}）' if suffix else ''}"


def extract_award_facts(text: str, tenant_id: int) -> list[ExtractedAwardFact]:
    resp = extract_completion(
        messages=[
            {"role": "system", "content": PROFILE_MATERIAL_AWARD_PROMPT_V1},
            {"role": "user", "content": text[:MATERIAL_TEXT_LIMIT]},
        ],
        temperature=0.0,
        scene="profile_suggest",
        tenant_id=tenant_id,
    )
    content = resp.choices[0].message.content or ""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 未返回有效 JSON")
    parsed = AwardExtraction.model_validate(json.loads(content[start : end + 1]))
    return [fact for fact in parsed.facts if evidence_is_grounded(fact.evidence_quote, text)]


def run_material_extraction(session: Session, material_id: int) -> int:
    """抽取单份材料并写入 pending 事实，返回新增数量；支持失败后幂等重试。"""
    material = session.get(ProfileMaterial, material_id)
    if material is None:
        raise ValueError(f"画像材料 {material_id} 不存在")
    if not material.parsed_text:
        raise ValueError("材料没有可提取文本")
    if material.document_type != "award_notice":
        raise ValueError("当前版本仅支持从中标/成交通知材料抽取案例")

    existing_fact_ids = session.scalars(
        select(ProfileEvidence.fact_id).where(ProfileEvidence.material_id == material.id)
    ).all()
    confirmed = session.scalar(
        select(ProfileFact.id).where(
            ProfileFact.id.in_(existing_fact_ids), ProfileFact.status == "confirmed"
        )
    ) if existing_fact_ids else None
    if confirmed:
        raise ValueError("该材料已有已确认事实，不能覆盖")
    if existing_fact_ids:
        session.execute(delete(ProfileEvidence).where(ProfileEvidence.material_id == material.id))
        session.flush()
        for fact_id in existing_fact_ids:
            has_other_evidence = session.scalar(
                select(ProfileEvidence.id).where(ProfileEvidence.fact_id == fact_id).limit(1)
            )
            if not has_other_evidence:
                session.execute(delete(ProfileFact).where(ProfileFact.id == fact_id))

    material.parse_status = "extracting"
    material.error = None
    facts = extract_award_facts(material.parsed_text, material.tenant_id)
    for extracted in facts:
        confidence = {
            "winner": 0.95,
            "supplier": 0.9,
            "consortium_member": 0.8,
            "candidate": 0.55,
            "mentioned": 0.25,
            "unknown": 0.4,
        }[extracted.company_role]
        key = canonical_case_key(extracted.project_name)
        fact = session.scalar(
            select(ProfileFact).where(
                ProfileFact.tenant_id == material.tenant_id,
                ProfileFact.fact_type == "project_case",
                ProfileFact.canonical_key == key,
                ProfileFact.status != "rejected",
            )
        )
        if fact is None:
            value = extracted.model_dump(exclude={"evidence_quote", "evidence_page"})
            fact = ProfileFact(
                tenant_id=material.tenant_id,
                fact_type="project_case",
                canonical_key=key,
                value=value,
                confidence=confidence,
                source_strength="document_proof",
                status="pending",
            )
            session.add(fact)
            session.flush()
        else:
            fact.confidence = max(fact.confidence, confidence)
        already_linked = session.scalar(
            select(ProfileEvidence.id).where(
                ProfileEvidence.fact_id == fact.id,
                ProfileEvidence.material_id == material.id,
            )
        )
        if already_linked:
            continue
        session.add(
            ProfileEvidence(
                tenant_id=material.tenant_id,
                fact_id=fact.id,
                material_id=material.id,
                page=evidence_page(extracted.evidence_quote, material.parsed_text),
                quote=extracted.evidence_quote,
                metadata_json={"company_role": extracted.company_role},
            )
        )
    material.parse_status = "extracted" if facts else "no_facts"
    return len(facts)


def project_confirmed_case(session: Session, fact: ProfileFact, value: dict) -> None:
    """将用户确认的结构化案例投影到兼容画像快照，供现有匹配链路立即使用。"""
    from app.matching.profiles import upsert_profile
    from app.models import CompanyProfile, Tenant

    case = ProjectCaseValue.model_validate(value)
    profile = session.scalar(
        select(CompanyProfile).where(CompanyProfile.tenant_id == fact.tenant_id)
    )
    tenant = session.get(Tenant, fact.tenant_id)
    data = dict(profile.data or {}) if profile else {}
    data.setdefault("name", tenant.name)
    for key, default in (
        ("description", ""),
        ("products", []),
        ("services", []),
        ("industries", []),
        ("regions", []),
        ("certifications", []),
        ("brands", []),
        ("cases_text", ""),
        ("filter", {"regions": [], "min_budget": None}),
    ):
        data.setdefault(key, default)

    case_line = format_case_line(case)
    existing_lines = [line.strip() for line in data["cases_text"].splitlines() if line.strip()]
    if case_line not in existing_lines:
        existing_lines.append(case_line)
    data["cases_text"] = "\n".join(existing_lines)
    data["services"] = list(dict.fromkeys([*(data.get("services") or []), *case.services]))
    upsert_profile(session, fact.tenant_id, data)
