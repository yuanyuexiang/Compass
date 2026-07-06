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


class MatchScoreCard(BaseModel):
    match_score: float = Field(ge=0, le=100)
    star: int = Field(ge=1, le=5)
    advice: str
    reasons: list[MatchReason] = []
    risks: dict[str, RiskItem] = {}

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
