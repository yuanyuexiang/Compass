"""公共数据层模型（租户无关，见 tech-design.md §6）。租户层模型在 M3 加入。"""

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.db import Base


class SystemSetting(Base):
    """系统级键值配置（如自动采集间隔），管理员可在后台修改、即时生效。"""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value = mapped_column(JSONB, nullable=True)


class AnnouncementStatus(enum.StrEnum):
    """流水线状态机（tech-design.md §4）。"""

    CRAWLED = "crawled"
    CLEANED = "cleaned"
    ATTACHMENTS_PARSED = "attachments_parsed"
    AI_EXTRACTED = "ai_extracted"
    EMBEDDED = "embedded"
    PUBLISHED = "published"
    FAILED = "failed"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)  # 唯一标识（种子幂等/日志用）
    display_name: Mapped[str | None] = mapped_column(String(128))  # 中文显示名，界面主标签
    adapter: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cron: Mapped[str | None] = mapped_column(String(64))
    min_interval_seconds: Mapped[float] = mapped_column(Float, default=3.0)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    announcements: Mapped[list["Announcement"]] = relationship(back_populates="source")


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    ann_type: Mapped[str | None] = mapped_column(String(32))
    region: Mapped[str | None] = mapped_column(String(32))
    buyer: Mapped[str | None] = mapped_column(Text)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_html: Mapped[str | None] = mapped_column(Text)
    clean_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), default=AnnouncementStatus.CRAWLED.value, index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[Source] = relationship(back_populates="announcements")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="announcement")
    project: Mapped["Project | None"] = relationship(back_populates="announcement")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(128))
    parsed_text: Mapped[str | None] = mapped_column(Text)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    announcement: Mapped[Announcement] = relationship(back_populates="attachments")


class Project(Base):
    """AI 结构化后的项目（M2 起填充；fields 内每字段含 value/evidence/confidence）。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id"), unique=True, index=True
    )
    fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    category: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    announcement: Mapped[Announcement] = relationship(back_populates="project")
