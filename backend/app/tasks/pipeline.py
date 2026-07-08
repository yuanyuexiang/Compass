"""公共层流水线（tech-design.md §4）。

纯函数（run_*，可同步调用、可测试）+ Celery 薄包装（*_task）。
状态机：crawled → cleaned → attachments_parsed →（M2）ai_extracted → embedded → published
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import embeddings
from app.ai.extract import build_input, extract_project
from app.core import storage
from app.core.db import session_scope
from app.crawler.base import SourceAdapter, get_adapter, url_fingerprint
from app.matching.engine import run_match
from app.models import (
    Announcement,
    AnnouncementStatus,
    Attachment,
    CompanyProfile,
    Project,
    Source,
    Tenant,
)
from app.notify.dispatcher import dispatch_daily_digest, dispatch_match
from app.parsing.clean import html_to_text
from app.parsing.documents import parse_attachment
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


def run_crawl_source(session: Session, source: Source, limit: int | None = None) -> list[int]:
    """采集一个源的公告列表，新公告入库（status=crawled），返回新增 ID 列表。"""
    adapter = get_adapter(source.adapter, source.config)
    new_ids: list[int] = []
    try:
        for raw in adapter.list_announcements():
            if limit is not None and len(new_ids) >= limit:
                break
            fp = url_fingerprint(raw.url)
            exists = session.scalar(select(Announcement.id).where(Announcement.fingerprint == fp))
            if exists:
                continue
            ann = Announcement(
                source_id=source.id,
                url=raw.url,
                fingerprint=fp,
                title=raw.title,
                ann_type=raw.ann_type,
                region=raw.region,
                buyer=raw.buyer,
                publish_time=raw.publish_time,
                status=AnnouncementStatus.CRAWLED.value,
            )
            session.add(ann)
            session.flush()
            new_ids.append(ann.id)
    finally:
        adapter.close()
    logger.info("crawl source=%s new=%d", source.name, len(new_ids))
    return new_ids


def run_fetch_and_clean(session: Session, announcement_id: int) -> None:
    """抓详情 → 清洗正文 → cleaned → 附件下载/解析 → attachments_parsed。"""
    ann = session.get(Announcement, announcement_id)
    if ann is None:
        raise ValueError(f"announcement {announcement_id} 不存在")
    adapter = get_adapter(ann.source.adapter, ann.source.config)
    try:
        ann.raw_html = adapter.fetch_detail(ann.url)
        ann.clean_text = html_to_text(ann.raw_html, adapter.content_selectors())
        ann.status = AnnouncementStatus.CLEANED.value
        _process_attachments(session, ann, adapter)
        ann.status = AnnouncementStatus.ATTACHMENTS_PARSED.value
        ann.error = None
    except Exception as exc:
        ann.status = AnnouncementStatus.FAILED.value
        ann.error = str(exc)[:2000]
        raise
    finally:
        adapter.close()


def _process_attachments(session: Session, ann: Announcement, adapter: SourceAdapter) -> None:
    """下载并解析附件；单个附件失败只标记该附件，不拖垮整条公告。"""
    for link in adapter.extract_attachments(ann.raw_html or "", ann.url):
        att = Attachment(announcement_id=ann.id, url=link.url, filename=link.filename)
        session.add(att)
        try:
            resp = adapter.get(link.url)
            data = resp.content
            att.content_type = resp.headers.get("content-type")
            att.object_key = storage.put_bytes(
                f"{ann.id}/{url_fingerprint(link.url)[:16]}-{link.filename}",
                data,
                att.content_type or "application/octet-stream",
            )
            att.parsed_text, att.needs_ocr = parse_attachment(link.filename, data)
            att.status = "needs_ocr" if att.needs_ocr else "parsed"
        except Exception as exc:
            att.status = "failed"
            logger.warning("附件处理失败 ann=%s url=%s: %s", ann.id, link.url, exc)


@celery.task(name="app.tasks.pipeline.crawl_all_sources")
def crawl_all_sources() -> None:
    with session_scope() as session:
        source_ids = session.scalars(select(Source.id).where(Source.enabled)).all()
    for sid in source_ids:
        crawl_source_task.delay(sid)


@celery.task(name="app.tasks.pipeline.crawl_source", max_retries=2, default_retry_delay=300)
def crawl_source_task(source_id: int) -> None:
    from datetime import UTC, datetime

    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None or not source.enabled:
            return
        new_ids = run_crawl_source(session, source)
        source.last_run_at = datetime.now(UTC)
    for ann_id in new_ids:
        fetch_and_clean_task.delay(ann_id)


def run_ai_extract(session: Session, announcement_id: int) -> Project:
    """AI 理解：正文+附件文本 → 十二字段/分类/摘要 → ai_extracted。"""
    ann = session.get(Announcement, announcement_id)
    if ann is None or not ann.clean_text:
        raise ValueError(f"announcement {announcement_id} 不存在或未清洗")
    attachment_texts = [a.parsed_text for a in ann.attachments if a.parsed_text]
    try:
        result = extract_project(build_input(ann.title, ann.clean_text, attachment_texts))
        project = session.scalar(select(Project).where(Project.announcement_id == ann.id))
        if project is None:
            project = Project(announcement_id=ann.id)
            session.add(project)
        dump = result.model_dump()
        project.summary = dump.pop("summary")
        project.category = dump.pop("classification")
        project.fields = dump
        ann.status = AnnouncementStatus.AI_EXTRACTED.value
        ann.error = None
        return project
    except Exception as exc:
        ann.status = AnnouncementStatus.FAILED.value
        ann.error = str(exc)[:2000]
        raise


@celery.task(name="app.tasks.pipeline.fetch_and_clean", max_retries=2, default_retry_delay=120)
def fetch_and_clean_task(announcement_id: int) -> None:
    with session_scope() as session:
        run_fetch_and_clean(session, announcement_id)
    ai_extract_task.delay(announcement_id)


def run_embed_and_publish(session: Session, announcement_id: int) -> None:
    """向量化（可用时）→ embedded → published。无 embedding Key 时直接发布，
    匹配退化为规则+LLM 二级漏斗（见 app/ai/embeddings.py）。"""
    ann = session.get(Announcement, announcement_id)
    project = session.scalar(select(Project).where(Project.announcement_id == announcement_id))
    if ann is None or project is None:
        raise ValueError(f"announcement {announcement_id} 无对应 project")
    if embeddings.available() and project.summary:
        project.embedding = embeddings.embed_texts([project.summary])[0]
        ann.status = AnnouncementStatus.EMBEDDED.value
    ann.status = AnnouncementStatus.PUBLISHED.value


@celery.task(name="app.tasks.pipeline.ai_extract", max_retries=2, default_retry_delay=60)
def ai_extract_task(announcement_id: int) -> None:
    with session_scope() as session:
        run_ai_extract(session, announcement_id)
    publish_task.delay(announcement_id)


@celery.task(name="app.tasks.pipeline.publish", max_retries=2, default_retry_delay=60)
def publish_task(announcement_id: int) -> None:
    """发布并 fan-out 到各订阅租户做匹配（公共层→租户层的衔接点，§2 架构图）。"""
    with session_scope() as session:
        run_embed_and_publish(session, announcement_id)
        project = session.scalar(
            select(Project.id).where(Project.announcement_id == announcement_id)
        )
        tenant_ids = session.scalars(
            select(Tenant.id)
            .join(CompanyProfile, CompanyProfile.tenant_id == Tenant.id)
            .where(Tenant.enabled)
        ).all()
    for tenant_id in tenant_ids:
        match_project_task.delay(project, tenant_id)


@celery.task(name="app.tasks.pipeline.match_project", max_retries=2, default_retry_delay=60)
def match_project_task(project_id: int, tenant_id: int) -> None:
    with session_scope() as session:
        match = run_match(session, project_id, tenant_id)
        if match is not None:
            dispatch_match(session, match)


@celery.task(name="app.tasks.pipeline.daily_digest")
def daily_digest_task() -> None:
    with session_scope() as session:
        tenant_ids = session.scalars(select(Tenant.id).where(Tenant.enabled)).all()
        for tenant_id in tenant_ids:
            dispatch_daily_digest(session, tenant_id)
