"""LLM 精排评分卡 Schema（tech-design.md §5.2）。

风险六项对应 prd.md §5.6。沿用提取模块的教训：对模型输出做宽容解析。
"""

from pydantic import BaseModel, Field, field_validator

RISK_KEYS = [
    "brand_restriction",  # 品牌限制
    "exclusivity",  # 排他性条件
    "special_qualification",  # 特殊资质
    "insufficient_budget",  # 预算不足
    "high_competition",  # 竞争激烈
    "rejection_risk",  # 废标风险
]

ADVICE_VALUES = ("建议参与", "谨慎参与", "不建议参与")

DIMENSION_LIMITS = {
    "business_fit": 35,
    "case_evidence": 20,
    "product_service": 15,
    "qualification": 15,
    "delivery_region": 5,
    "commercial_preference": 10,
}

FIT_LEVELS = ("high", "medium", "partial", "none")
QUALIFICATION_STATUSES = ("satisfied", "unknown", "missing")
DELIVERY_MODES = ("independent", "partner", "unsuitable")


class RiskItem(BaseModel):
    hit: bool = False
    evidence: str | None = None
    severity: str | None = None  # 高/中/低

    @field_validator("hit", mode="before")
    @classmethod
    def coerce_hit(cls, v):
        if isinstance(v, str):
            return v in ("true", "True", "是", "命中", "1")
        return bool(v)


class MatchReason(BaseModel):
    point: str
    evidence: str | None = None

    @field_validator("point", mode="before")
    @classmethod
    def unwrap(cls, v):
        if isinstance(v, dict) and "value" in v:
            return v["value"]
        return v


class DimensionScore(BaseModel):
    """LLM 对单个维度的事实判断；分值上限由代码再次约束。"""

    score: float = Field(ge=0)
    evidence: str | None = None
    note: str = ""


class MatchAssessment(BaseModel):
    """LLM 原始判断。总分、星级和建议不交给模型计算。"""

    dimensions: dict[str, DimensionScore]
    fit_level: str = "partial"
    qualification_status: str = "unknown"
    delivery_mode: str = "independent"
    reasons: list[MatchReason] = []
    risks: dict[str, RiskItem] = {}

    @field_validator("dimensions", mode="before")
    @classmethod
    def keep_known_dimensions(cls, v):
        if not isinstance(v, dict):
            return {}
        return {k: v[k] for k in DIMENSION_LIMITS if k in v}

    @field_validator("fit_level", mode="before")
    @classmethod
    def normalize_fit_level(cls, v):
        return v if v in FIT_LEVELS else "partial"

    @field_validator("qualification_status", mode="before")
    @classmethod
    def normalize_qualification_status(cls, v):
        return v if v in QUALIFICATION_STATUSES else "unknown"

    @field_validator("delivery_mode", mode="before")
    @classmethod
    def normalize_delivery_mode(cls, v):
        return v if v in DELIVERY_MODES else "independent"

    @field_validator("risks", mode="before")
    @classmethod
    def keep_assessment_risks(cls, v):
        if not isinstance(v, dict):
            return {}
        return {k: v[k] for k in RISK_KEYS if k in v}


class MatchScoreCard(BaseModel):
    match_score: float = Field(ge=0, le=100)
    # v2 起 star 不再由模型输出（消除映射算错的来源），engine 按 match_score 映射后回填
    star: int = Field(default=0, ge=0, le=5)
    advice: str
    reasons: list[MatchReason] = []
    risks: dict[str, RiskItem] = {}
    dimensions: dict[str, DimensionScore] = {}
    fit_level: str = "partial"
    qualification_status: str = "unknown"
    delivery_mode: str = "independent"
    vector_similarity: float | None = None

    @field_validator("advice", mode="before")
    @classmethod
    def normalize_advice(cls, v):
        if isinstance(v, dict) and "value" in v:
            v = v["value"]
        return v if v in ADVICE_VALUES else "谨慎参与"

    @field_validator("risks", mode="before")
    @classmethod
    def keep_known_risks(cls, v):
        if not isinstance(v, dict):
            return {}
        return {k: v[k] for k in RISK_KEYS if k in v}
