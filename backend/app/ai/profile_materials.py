"""企业上传画像材料 → 原子事实与证据。

支持履约证明与企业能力资料。抽取结果始终是 pending，只有用户确认后才进入正式画像。
"""

import json
import re

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.llm_config import extract_completion
from app.ai.prompts.profile_material_award_v1 import PROFILE_MATERIAL_AWARD_PROMPT_V1
from app.ai.prompts.profile_material_capability_v1 import PROFILE_MATERIAL_CAPABILITY_PROMPT_V1
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
CAPABILITY_FACT_TYPES = {
    "product_capability",
    "service_capability",
    "industry_capability",
    "certification",
    "brand_partnership",
    "company_description",
}
DOCUMENT_SOURCE_STRENGTH = {
    "award_notice": "contract_proof",
    "contract": "contract_proof",
    "acceptance_report": "acceptance_proof",
    "qualification": "certificate_proof",
    "case_study": "case_supported",
    "company_presentation": "self_declared",
    "solution": "self_declared",
    "product_manual": "self_declared",
    "whitepaper": "self_declared",
    "other": "self_declared",
}
SOURCE_STRENGTH_RANK = {
    "self_declared": 1,
    "case_supported": 2,
    "document_proof": 3,
    "contract_proof": 3,
    "certificate_proof": 3,
    "acceptance_proof": 4,
    "tenant_confirmed": 5,
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


class ExtractedCapabilityFact(BaseModel):
    fact_type: str
    value: dict
    evidence_quote: str = Field(min_length=2, max_length=500)
    evidence_page: int | None = Field(default=None, ge=1)


def _unwrap_llm_value(value):
    """宽容处理模型常见的 {value, evidence, confidence} 包装。"""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def validate_fact_value(fact_type: str, value: dict) -> dict:
    """确认前的最小结构校验；保留扩展字段，拒绝没有主体内容的事实。"""
    cleaned = {key: _unwrap_llm_value(item) for key, item in value.items()}
    if fact_type == "project_case":
        return ProjectCaseValue.model_validate(cleaned).model_dump()
    if fact_type == "company_description":
        description = str(cleaned.get("description") or "").strip()
        if len(description) < 2:
            raise ValueError("企业简介不能为空")
        return {"description": description}
    name = str(cleaned.get("name") or "").strip()
    if len(name) < 2:
        raise ValueError("事实名称不能为空")
    cleaned["name"] = name
    if fact_type in {
        "product_capability",
        "service_capability",
        "industry_capability",
    }:
        status = cleaned.get("status", "current")
        if status not in {"current", "planned"}:
            raise ValueError("能力状态无效")
        return {
            "name": name,
            "description": str(cleaned.get("description") or "").strip(),
            "status": status,
        }
    if fact_type == "certification":
        return {
            "name": name,
            "issuer": cleaned.get("issuer") or None,
            "valid_until": cleaned.get("valid_until") or None,
        }
    if fact_type == "brand_partnership":
        return {
            "name": name,
            "relationship": str(cleaned.get("relationship") or "其他").strip(),
        }
    raise ValueError("不支持的事实类型")


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


def canonical_fact_key(fact_type: str, value: dict) -> str:
    raw = value.get("project_name") or value.get("name") or value.get("description") or ""
    return f"{fact_type}:{canonical_case_key(str(raw))}"[:256]


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
        scene="profile_material",
        tenant_id=tenant_id,
    )
    content = resp.choices[0].message.content or ""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 未返回有效 JSON")
    parsed = AwardExtraction.model_validate(json.loads(content[start : end + 1]))
    return [fact for fact in parsed.facts if evidence_is_grounded(fact.evidence_quote, text)]


def extract_capability_facts(text: str, tenant_id: int) -> list[ExtractedCapabilityFact]:
    resp = extract_completion(
        messages=[
            {"role": "system", "content": PROFILE_MATERIAL_CAPABILITY_PROMPT_V1},
            {"role": "user", "content": text[:MATERIAL_TEXT_LIMIT]},
        ],
        temperature=0.0,
        scene="profile_material",
        tenant_id=tenant_id,
    )
    content = resp.choices[0].message.content or ""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 未返回有效 JSON")
    payload = json.loads(content[start : end + 1])
    raw_facts = payload.get("facts", []) if isinstance(payload, dict) else []
    if not isinstance(raw_facts, list):
        return []
    facts: list[ExtractedCapabilityFact] = []
    for raw in raw_facts:
        if not isinstance(raw, dict):
            continue
        fact_type = _unwrap_llm_value(raw.get("fact_type"))
        if fact_type not in CAPABILITY_FACT_TYPES | {"project_case"}:
            continue
        raw_value = _unwrap_llm_value(raw.get("value"))
        if not isinstance(raw_value, dict):
            continue
        try:
            value = validate_fact_value(fact_type, raw_value)
            fact = ExtractedCapabilityFact.model_validate(
                {
                    "fact_type": fact_type,
                    "value": value,
                    "evidence_quote": _unwrap_llm_value(raw.get("evidence_quote")),
                    "evidence_page": _unwrap_llm_value(raw.get("evidence_page")),
                }
            )
        except (ValidationError, ValueError, TypeError):
            continue
        if evidence_is_grounded(fact.evidence_quote, text):
            facts.append(fact)
    return facts


def fact_confidence(fact_type: str, value: dict, source_strength: str) -> float:
    if fact_type == "project_case":
        return {
            "winner": 0.95,
            "supplier": 0.9,
            "consortium_member": 0.8,
            "candidate": 0.55,
            "mentioned": 0.25,
            "unknown": 0.4,
        }.get(value.get("company_role"), 0.4)
    confidence = {
        "self_declared": 0.65,
        "case_supported": 0.75,
        "contract_proof": 0.85,
        "certificate_proof": 0.9,
        "acceptance_proof": 0.95,
    }.get(source_strength, 0.6)
    return min(confidence, 0.35) if value.get("status") == "planned" else confidence


def material_source_strength(material: ProfileMaterial) -> str:
    """自动文件名分类只决定抽取 Prompt，不允许借文件名提升证据等级。"""
    if material.source_type == "auto_detected_document":
        return "self_declared"
    return DOCUMENT_SOURCE_STRENGTH.get(material.document_type, "self_declared")


def run_material_extraction(session: Session, material_id: int) -> int:
    """抽取单份材料并写入 pending 事实，返回新增数量；支持失败后幂等重试。"""
    material = session.get(ProfileMaterial, material_id)
    if material is None:
        raise ValueError(f"画像材料 {material_id} 不存在")
    if not material.parsed_text:
        raise ValueError("材料没有可提取文本")

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
    if material.document_type == "award_notice":
        facts = extract_award_facts(material.parsed_text, material.tenant_id)
    else:
        facts = extract_capability_facts(material.parsed_text, material.tenant_id)
    for extracted in facts:
        fact_type = getattr(extracted, "fact_type", "project_case")
        value = (
            extracted.model_dump(exclude={"fact_type", "evidence_quote", "evidence_page"})
            if fact_type == "project_case" and isinstance(extracted, ExtractedAwardFact)
            else extracted.value
        )
        company_role = value.get("company_role", "unknown")
        source_strength = material_source_strength(material)
        confidence = fact_confidence(fact_type, value, source_strength)
        key = canonical_fact_key(fact_type, value)
        fact = session.scalar(
            select(ProfileFact).where(
                ProfileFact.tenant_id == material.tenant_id,
                ProfileFact.fact_type == fact_type,
                ProfileFact.canonical_key == key,
                ProfileFact.status != "rejected",
            )
        )
        if fact is None:
            fact = ProfileFact(
                tenant_id=material.tenant_id,
                fact_type=fact_type,
                canonical_key=key,
                value=value,
                confidence=confidence,
                source_strength=source_strength,
                status="pending",
            )
            session.add(fact)
            session.flush()
        else:
            fact.confidence = max(fact.confidence, confidence)
            candidate_strength = source_strength
            if SOURCE_STRENGTH_RANK.get(candidate_strength, 0) > SOURCE_STRENGTH_RANK.get(
                fact.source_strength, 0
            ):
                fact.source_strength = candidate_strength
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
                metadata_json={
                    "company_role": company_role,
                    "document_type": material.document_type,
                },
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


def project_confirmed_fact(session: Session, fact: ProfileFact, value: dict) -> bool:
    """把经人工确认的多类事实投影到兼容画像字段。规划能力只保留事实，不参与匹配。"""
    if fact.fact_type == "project_case":
        if SOURCE_STRENGTH_RANK.get(fact.source_strength, 0) < SOURCE_STRENGTH_RANK[
            "case_supported"
        ]:
            return False
        project_confirmed_case(session, fact, value)
        return True

    from app.matching.profiles import upsert_profile
    from app.models import CompanyProfile, Tenant

    if value.get("status") == "planned":
        return False
    field_by_type = {
        "product_capability": "products",
        "service_capability": "services",
        "industry_capability": "industries",
        "certification": "certifications",
        "brand_partnership": "brands",
    }
    profile = session.scalar(
        select(CompanyProfile).where(CompanyProfile.tenant_id == fact.tenant_id)
    )
    tenant = session.get(Tenant, fact.tenant_id)
    data = dict(profile.data or {}) if profile else {"name": tenant.name}
    for key in ("products", "services", "industries", "regions", "certifications", "brands"):
        data.setdefault(key, [])
    data.setdefault("description", "")
    data.setdefault("cases_text", "")
    data.setdefault("filter", {"regions": [], "min_budget": None})
    if fact.fact_type == "company_description":
        description = str(value.get("description") or "").strip()
        if description and not data["description"]:
            data["description"] = description
        else:
            return False
    elif field := field_by_type.get(fact.fact_type):
        name = str(value.get("name") or "").strip()
        if name:
            data[field] = list(dict.fromkeys([*(data.get(field) or []), name]))
    upsert_profile(session, fact.tenant_id, data)
    return True
