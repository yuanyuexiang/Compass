"""匹配引擎单测：预算解析、规则过滤、评分卡宽容校验（LLM 精排实测见 scripts/dev_match.py）。"""

import json

from app.matching.engine import parse_budget_yuan, rule_filter
from app.matching.schemas import RISK_KEYS, MatchScoreCard


class FakeProject:
    def __init__(self, region=None, budget=None, main=None):
        self.fields = {
            "region": {"value": region},
            "budget": {"value": budget},
        }
        self.category = {"main": main}


def test_parse_budget_yuan():
    assert parse_budget_yuan("265.000000万元（人民币）") == 2_650_000
    assert parse_budget_yuan("3300万元") == 33_000_000
    assert parse_budget_yuan("4604800.45元") == 4_604_800.45
    assert parse_budget_yuan("1,200万") == 12_000_000
    assert parse_budget_yuan(None) is None
    assert parse_budget_yuan("面议") is None


def test_rule_filter_region():
    profile = {"filter": {"regions": ["江苏省"]}}
    ok, _ = rule_filter(FakeProject(region="江苏省/苏州市"), profile)
    assert ok
    ok, reason = rule_filter(FakeProject(region="广东省/广州市"), profile)
    assert not ok and "区域" in reason
    ok, _ = rule_filter(FakeProject(region=None), profile)  # 未知地区放行，交给精排
    assert ok
    ok, _ = rule_filter(FakeProject(region="广东省/广州市"), {"filter": {"regions": ["全国"]}})
    assert ok


def test_rule_filter_budget_and_category():
    profile = {"filter": {"min_budget": 1_000_000, "exclude_mains": ["服务类"]}}
    ok, reason = rule_filter(FakeProject(budget="50万元"), profile)
    assert not ok and "预算" in reason
    ok, _ = rule_filter(FakeProject(budget="500万元"), profile)
    assert ok
    ok, reason = rule_filter(FakeProject(main="服务类"), profile)
    assert not ok and "排除大类" in reason


def test_scorecard_tolerant_parsing():
    raw = {
        "match_score": 85,
        "star": 4,
        "advice": {"value": "建议参与"},  # 模型可能包对象 → 解包
        "reasons": [{"point": {"value": "装修资质对口"}, "evidence": "二级资质"}],
        "risks": {
            "brand_restriction": {"hit": "是", "evidence": "指定品牌", "severity": "中"},
            "unknown_extra": {"hit": True},  # 未知键 → 丢弃
        },
    }
    card = MatchScoreCard.model_validate_json(json.dumps(raw, ensure_ascii=False))
    assert card.advice == "建议参与"
    assert card.reasons[0].point == "装修资质对口"
    assert card.risks["brand_restriction"].hit is True
    assert "unknown_extra" not in card.risks


def test_scorecard_bad_advice_falls_back():
    card = MatchScoreCard(match_score=50, star=2, advice="随便看看")
    assert card.advice == "谨慎参与"
    assert RISK_KEYS[0] == "brand_restriction"
