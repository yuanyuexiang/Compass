"""画像材料测试：原文证据约束、案例规范化和 TXT 解析。"""

import json
import types

from app.ai import profile_materials
from app.ai.profile_materials import (
    ProjectCaseValue,
    canonical_case_key,
    evidence_page,
    format_case_line,
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
