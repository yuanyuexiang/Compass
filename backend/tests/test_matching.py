"""匹配引擎单测：预算解析、规则过滤、评分卡宽容校验（LLM 精排实测见 scripts/dev_match.py）。"""

import json
from types import SimpleNamespace

from app.matching import engine
from app.matching.engine import (
    finalize_assessment,
    parse_budget_yuan,
    rule_filter,
    select_relevant_excerpt,
)
from app.matching.schemas import RISK_KEYS, MatchAssessment, MatchScoreCard


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


def test_region_filter_clause():
    """商机查询的地区过滤条件——与画像/推荐口径统一（app.matching.profiles.region_filter_clause）。"""
    from sqlalchemy.dialects import postgresql

    from app.matching.profiles import region_filter_clause

    # 空列表 / 含「全国」→ 不加地区限制
    assert region_filter_clause([]) is None
    assert region_filter_clause(["全国"]) is None
    assert region_filter_clause(["全国", "江苏省"]) is None

    # 多地区 → OR；去「省/市」后缀；列表元数据 region 与结构化字段 region 两处都匹配
    clause = region_filter_clause(["江苏省", "浙江省"])
    assert clause is not None
    sql = str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "%江苏%" in sql and "%浙江%" in sql  # 已去掉「省」后缀
    assert sql.lower().count("ilike") == 4  # 2 地区 × 2 字段


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


def test_rule_filter_region_suffix_variants():
    """公告写「广西/南宁」、画像写「广西壮族自治区」——按地名主干比较不误杀。"""
    profile = {"filter": {"regions": ["广西壮族自治区"]}}
    ok, _ = rule_filter(FakeProject(region="广西/南宁市"), profile)
    assert ok
    ok, _ = rule_filter(FakeProject(region="广西壮族自治区/南宁市"), profile)
    assert ok
    ok, reason = rule_filter(FakeProject(region="湖南省/长沙市"), profile)
    assert not ok and "区域" in reason


def _assessment(**overrides) -> MatchAssessment:
    raw = {
        "dimensions": {
            "business_fit": {"score": 34, "evidence": "核心业务"},
            "case_evidence": {"score": 18, "evidence": "同类案例"},
            "product_service": {"score": 14},
            "qualification": {"score": 10, "note": "部分资质待确认"},
            "delivery_region": {"score": 5},
            "commercial_preference": {"score": 9},
        },
        "fit_level": "high",
        "qualification_status": "unknown",
        "delivery_mode": "independent",
        "reasons": [],
        "risks": {},
    }
    raw.update(overrides)
    return MatchAssessment.model_validate(raw)


def test_finalize_assessment_calculates_score_and_advice():
    card = finalize_assessment(_assessment(), similarity=0.21)
    assert card.match_score == 90
    assert card.star == 5
    assert card.advice == "建议参与"
    assert card.vector_similarity == 0.21
    # 画像未列出资质只表示未知，不应自动封顶。
    assert card.qualification_status == "unknown"


def test_finalize_assessment_applies_business_caps():
    partner = finalize_assessment(_assessment(delivery_mode="partner"))
    assert partner.match_score == 79
    assert partner.star == 3
    assert partner.advice == "谨慎参与"

    partial = finalize_assessment(_assessment(fit_level="partial"))
    assert partial.match_score == 49
    assert partial.advice == "不建议参与"

    missing = finalize_assessment(_assessment(qualification_status="missing"))
    assert missing.match_score == 49


def test_finalize_assessment_clamps_dimension_scores():
    assessment = _assessment()
    assessment.dimensions["business_fit"].score = 100
    card = finalize_assessment(assessment)
    assert card.match_score == 91  # business_fit 按 35 分上限，而不是模型给出的 100


def test_select_relevant_excerpt_finds_late_qualification_section():
    text = "\n".join(
        ["项目概况", "普通开场内容"]
        + [f"无关内容{i}" for i in range(30)]
        + ["申请人的资格要求", "须具备电子与智能化工程专业承包二级", "下一章节"]
    )
    excerpt = select_relevant_excerpt(text, max_chars=300)
    assert "项目概况" in excerpt
    assert "电子与智能化工程专业承包二级" in excerpt
    assert len(excerpt) <= 300


def test_llm_rerank_accepts_fenced_json_and_computes_total(monkeypatch):
    payload = _assessment().model_dump(mode="json")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=f"```json\n{json.dumps(payload)}\n```"))]
    )
    monkeypatch.setattr(engine, "extract_completion", lambda **kwargs: response)
    card = engine.llm_rerank("input", similarity=0.42)
    assert card.match_score == 90
    assert card.star == 5
    assert card.vector_similarity == 0.42
