"""AI 理解环节的结构化输出 Schema（prd.md §5.2 十二字段 + §5.3 分类）。

每个字段带 evidence（原文片段）与 confidence（0–1），支撑「AI 输出可追溯」原则；
低置信度字段在后台标黄供人工复核（M4）。
"""

from pydantic import BaseModel, Field, field_validator


class ExtractedField(BaseModel):
    value: str | None = None  # 未提及时为 null，禁止编造
    evidence: str | None = None  # 依据的原文片段（截取，非改写）
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Classification(BaseModel):
    main: str  # IT类 / 软件类 / 工程类 / 货物类 / 服务类 / 其他
    sub: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("main", "sub", mode="before")
    @classmethod
    def unwrap_field_object(cls, v):
        """模型常把 main/sub 也包成 {value, evidence, confidence} 对象，宽容解包。"""
        if isinstance(v, dict) and "value" in v:
            return v["value"]
        return v


class ExtractionResult(BaseModel):
    project_name: ExtractedField  # 项目名称
    tender_org: ExtractedField  # 招标/采购单位
    publish_time: ExtractedField  # 发布时间
    bid_deadline: ExtractedField  # 投标截止/开标时间
    budget: ExtractedField  # 项目预算（value 统一为「N元」或原文金额表述）
    industry: ExtractedField  # 所属行业
    region: ExtractedField  # 地区（省/市）
    product_category: ExtractedField  # 产品类别
    service_type: ExtractedField  # 服务类型
    contact: ExtractedField  # 联系方式
    attachments_info: ExtractedField  # 附件信息
    requirements: ExtractedField  # 招标要求（资质/业绩/技术要点摘要）
    classification: Classification
    summary: str  # 规范化一句话摘要（标题+内容+行业+地区+预算），供向量化
