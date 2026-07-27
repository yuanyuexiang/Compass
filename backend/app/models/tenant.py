"""租户层模型（tech-design.md §6，均含 tenant_id）。"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    # enabled 是流水线/查询的运行开关；status 记录审批生命周期，两者由审批操作联动
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # pending（申请待审批）/ active（已开通）/ disabled（已停用）
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    profile: Mapped["CompanyProfile | None"] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # platform_admin / tenant_admin / sales
    role: Mapped[str] = mapped_column(String(32), default="sales")
    email: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="users")


class CompanyProfile(Base):
    """企业能力画像：data 为结构化字段，summary_text 供 LLM 精排 Prompt 与向量化。"""

    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary_text: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped[Tenant] = relationship(back_populates="profile")


class ProfileChunk(Base):
    __tablename__ = "profile_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True)


class MatchResult(Base):
    __tablename__ = "match_results"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    match_score: Mapped[float] = mapped_column(Float)
    star: Mapped[int] = mapped_column(Integer, index=True)
    advice: Mapped[str] = mapped_column(String(16))  # 建议参与/谨慎参与/不建议参与
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    risks: Mapped[dict] = mapped_column(JSONB, default=dict)
    follow_status: Mapped[str] = mapped_column(String(16), default="待看")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), unique=True, index=True)
    min_star: Mapped[int] = mapped_column(Integer, default=4)
    immediate: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    channels: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 关注的数据源 id 列表；空 = 不限（全部源）。采集全局共享，此处只影响该租户查询/推荐口径
    source_ids: Mapped[list] = mapped_column(JSONB, default=list)


class LlmUsage(Base):
    """LLM 调用记账：配额判断的依据，也是将来商业化计费的底账。

    tenant_id 为空表示公共层调用（如字段提取，全租户共享成本）。
    """

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # extract / match / nl_search / profile_suggest / source_suggest
    scene: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    related_match_id: Mapped[int | None] = mapped_column(BigInteger)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="sent")  # sent/failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
