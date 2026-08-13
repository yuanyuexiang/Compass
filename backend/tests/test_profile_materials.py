"""画像材料测试：原文证据约束、案例规范化和 TXT 解析。"""

import json
import types

from app.ai import profile_materials
from app.ai.profile_materials import (
    ProjectCaseValue,
    canonical_case_key,
    evidence_page,
    fact_confidence,
    format_case_line,
    validate_fact_value,
)
from app.parsing.documents import parse_attachment


def _completion(payload: dict):
    return types.SimpleNamespace(
        choices=[
            types.SimpleNamespace(
                message=types.SimpleNamespace(content=f"```json\n{json.dumps(payload)}\n```")
            )
        ]
    )


def test_extract_award_facts_keeps_only_grounded_evidence(monkeypatch):
    text = "[第1页]\n项目名称：智慧校园改造项目\n确定某公司为本项目中标单位。"
    payload = {
        "facts": [
            {
                "project_name": "智慧校园改造项目",
                "company_role": "winner",
                "customer": "某学校",
                "amount_yuan": 2_000_000,
                "region": "江苏省",
                "awarded_at": "2026-07",
                "services": ["综合布线", "综合布线"],
                "evidence_quote": "确定某公司为本项目中标单位。",
                "evidence_page": 1,
            },
            {
                "project_name": "模型编造的项目",
                "company_role": "winner",
                "services": [],
                "evidence_quote": "原文中不存在的证据",
                "evidence_page": 1,
            },
        ]
    }
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _completion(payload)

    monkeypatch.setattr(profile_materials, "extract_completion", fake_completion)
    facts = profile_materials.extract_award_facts(text, tenant_id=7)
    assert len(facts) == 1
    assert facts[0].project_name == "智慧校园改造项目"
    assert facts[0].services == ["综合布线"]
    assert evidence_page(facts[0].evidence_quote, text) == 1
    assert captured["scene"] == "profile_material"


def test_extract_capability_facts_marks_grounded_planned_capability(monkeypatch):
    text = "[第2页]\n未来计划推出园区能耗管理平台。"
    payload = {
        "facts": [
            {
                "fact_type": "model_invented_type",
                "value": {"name": "坏类型"},
                "evidence_quote": "未来计划推出园区能耗管理平台。",
            },
            {
                "fact_type": "service_capability",
                "value": {"description": "缺少名称", "status": "current"},
                "evidence_quote": "未来计划推出园区能耗管理平台。",
            },
            {
                "fact_type": {"value": "product_capability", "confidence": 0.9},
                "value": {
                    "name": {"value": "园区能耗管理平台"},
                    "description": "能耗管理",
                    "status": "planned",
                },
                "evidence_quote": {"value": "未来计划推出园区能耗管理平台。"},
                "evidence_page": 2,
            },
            {
                "fact_type": "service_capability",
                "value": {"name": "虚构服务", "status": "current"},
                "evidence_quote": "原文没有这句话",
                "evidence_page": 2,
            },
        ]
    }
    monkeypatch.setattr(profile_materials, "extract_completion", lambda **_: _completion(payload))

    facts = profile_materials.extract_capability_facts(text, tenant_id=7)
    assert len(facts) == 1
    assert facts[0].fact_type == "product_capability"
    assert facts[0].value["status"] == "planned"
    assert evidence_page(facts[0].evidence_quote, text) == 2


def test_capability_confidence_uses_evidence_strength_not_company_role():
    assert fact_confidence("certification", {"name": "ISO27001"}, "certificate_proof") == 0.9
    assert fact_confidence("product_capability", {"status": "current"}, "self_declared") == 0.65
    assert fact_confidence("product_capability", {"status": "planned"}, "acceptance_proof") == 0.35
    assert fact_confidence("project_case", {"company_role": "candidate"}, "contract_proof") == 0.55


def test_validate_fact_value_normalizes_wrappers_and_drops_extra_fields():
    value = validate_fact_value(
        "product_capability",
        {
            "name": {"value": "智慧园区平台"},
            "description": {"value": "园区运营"},
            "status": {"value": "current"},
            "services": "错误类型不应透传",
        },
    )
    assert value == {"name": "智慧园区平台", "description": "园区运营", "status": "current"}


def test_case_normalization_and_display():
    case = ProjectCaseValue(
        project_name="某医院弱电改造",
        company_role="winner",
        amount_yuan=4_600_000,
        services=["综合布线", "机房改造"],
    )
    assert canonical_case_key("某医院-弱电改造（一期）") == "某医院弱电改造一期"
    assert format_case_line(case) == "某医院弱电改造（460万元，综合布线、机房改造）"


def test_parse_txt_profile_material():
    text, needs_ocr = parse_attachment("中标通知.txt", "确定我司中标".encode())
    assert text == "确定我司中标"
    assert needs_ocr is False
