"""日志模型：操作日志（audit_logs，谁做了什么）+ 运行日志（system_events，流水线事件）。

均为公共层表；audit_logs 带 tenant_id 供租户侧过滤查询。detail 用通用 JSON
（而非 JSONB）：无需在其上建索引，且 SQLite 单测可直接建表。
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64))  # 快照，用户删除后仍可读
    action: Mapped[str] = mapped_column(String(64), index=True)  # 结构化键，如 tenant.approve
    target: Mapped[str | None] = mapped_column(String(255))  # 如 "tenant:12 某某公司"
    detail: Mapped[dict | None] = mapped_column(JSON)  # 变更摘要；严禁密码/密钥/JWT
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)  # info/warning/error
    event: Mapped[str] = mapped_column(String(64), index=True)  # 如 backpressure.pause
    message: Mapped[str] = mapped_column(Text)  # 中文可读描述
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
