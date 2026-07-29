"""公共层流水线（tech-design.md §4）。

纯函数（run_*，可同步调用、可测试）+ Celery 薄包装（*_task）。
状态机：crawled → cleaned → attachments_parsed →（M2）ai_extracted → embedded → published
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import embeddings
from app.ai.extract import build_input, extract_project
from app.core import storage
from app.core.db import session_scope
from app.crawler.base import SourceAdapter, ensure_cst, get_adapter, url_fingerprint
from app.matching.engine import run_match
from app.matching.profiles import tenant_watches_source
from app.models import (
    Announcement,
    AnnouncementStatus,
    Attachment,
    CompanyProfile,
    Project,
    Source,
    SourceStatus,
    Subscription,
    Tenant,
)
from app.notify.dispatcher import dispatch_daily_digest, dispatch_match
from app.opportunity import is_biddable
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
                biddable=is_biddable(raw.ann_type, raw.title),
                region=raw.region,
                buyer=raw.buyer,
                publish_time=ensure_cst(raw.publish_time),
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


def crawl_is_due(last_iso: str | None, interval_minutes: int, now: datetime) -> bool:
    """判断距上次自动采集是否已达到配置间隔（tick 调度的核心判据，纯函数可测）。"""
    if not last_iso:
        return True
    return now - datetime.fromisoformat(last_iso) >= timedelta(minutes=interval_minutes)


@celery.task(name="app.tasks.pipeline.crawl_tick")
def crawl_tick() -> None:
    """每分钟 tick：按管理员配置的间隔（system_settings）决定是否派发全量采集。"""
    from app.core.kv import (
        DEFAULT_CRAWL_INTERVAL_MINUTES,
        KEY_CRAWL_INTERVAL,
        KEY_LAST_AUTO_CRAWL,
        get_setting,
        set_setting,
    )

    now = datetime.now(UTC)
    with session_scope() as session:
        interval = int(
            get_setting(session, KEY_CRAWL_INTERVAL, DEFAULT_CRAWL_INTERVAL_MINUTES)
        )
        if not crawl_is_due(get_setting(session, KEY_LAST_AUTO_CRAWL), interval, now):
            return
        set_setting(session, KEY_LAST_AUTO_CRAWL, now.isoformat())
        source_ids = session.scalars(
            select(Source.id).where(Source.enabled, Source.status == SourceStatus.ACTIVE.value)
        ).all()
    logger.info("自动采集触发（间隔 %d 分钟，%d 个源）", interval, len(source_ids))
    for sid in source_ids:
        crawl_source_task.delay(sid)


@celery.task(name="app.tasks.pipeline.crawl_all_sources")
def crawl_all_sources() -> None:
    """手动全量采集（不影响自动调度的计时）。"""
    with session_scope() as session:
        source_ids = session.scalars(
            select(Source.id).where(Source.enabled, Source.status == SourceStatus.ACTIVE.value)
        ).all()
    for sid in source_ids:
        crawl_source_task.delay(sid)


@celery.task(name="app.tasks.pipeline.crawl_source", max_retries=2, default_retry_delay=300)
def crawl_source_task(source_id: int) -> None:
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None or not source.enabled or source.status != SourceStatus.ACTIVE.value:
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
    ann.biddable = is_biddable(ann.ann_type, ann.title)
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
        source_id, biddable = session.execute(
            select(Announcement.source_id, Announcement.biddable).where(
                Announcement.id == announcement_id
            )
        ).one()
        tenant_ids = session.scalars(
            select(Tenant.id)
            .join(CompanyProfile, CompanyProfile.tenant_id == Tenant.id)
            .where(Tenant.enabled)
        ).all()
        # 租户「关注的数据源」（订阅设置）：不关注该源的租户不派发匹配，省 LLM 也省噪音
        watched_map = dict(
            session.execute(select(Subscription.tenant_id, Subscription.source_ids)).all()
        )
    if biddable is False:  # 中标/成交/废标等结果公告：入库可查（开关放开），但不派发匹配
        return
    for tenant_id in tenant_ids:
        if not tenant_watches_source(watched_map.get(tenant_id) or [], source_id):
            continue
        match_project_task.delay(project, tenant_id)


@celery.task(name="app.tasks.pipeline.match_project", max_retries=2, default_retry_delay=60)
def match_project_task(project_id: int, tenant_id: int) -> None:
    with session_scope() as session:
        match = run_match(session, project_id, tenant_id)
        if match is not None:
            dispatch_match(session, match)


REMATCH_WINDOW_DAYS = 7


@celery.task(name="app.tasks.pipeline.rematch_tenant", max_retries=1, default_retry_delay=120)
def rematch_tenant_task(tenant_id: int) -> None:
    """画像变更后的重评估：对近 REMATCH_WINDOW_DAYS 天已发布、可投标、且在该租户
    关注源范围内的公告按新画像重跑匹配（run_match force：更新评分、保留跟进状态）。
    不发即时通知（防轰炸），新结果直接进工作台。受每日精排配额封顶。"""
    from app.matching.profiles import get_watched_source_ids

    since = datetime.now(UTC) - timedelta(days=REMATCH_WINDOW_DAYS)
    with session_scope() as session:
        watched = get_watched_source_ids(session, tenant_id)
        stmt = (
            select(Project.id)
            .join(Announcement, Project.announcement_id == Announcement.id)
            .where(
                Announcement.status == AnnouncementStatus.PUBLISHED.value,
                Announcement.biddable.isnot(False),
                Announcement.publish_time >= since,
            )
        )
        if watched:
            stmt = stmt.where(Announcement.source_id.in_(watched))
        project_ids = session.scalars(stmt).all()
    done = 0
    for pid in project_ids:
        with session_scope() as session:
            if run_match(session, pid, tenant_id, force=True) is not None:
                done += 1
    logger.info(
        "画像重评估完成 tenant=%s 窗口=%d天 候选=%d 产出/更新=%d",
        tenant_id, REMATCH_WINDOW_DAYS, len(project_ids), done,
    )


SWEEP_STUCK_AFTER = timedelta(hours=1)
SWEEP_FAILED_AFTER = timedelta(hours=6)
SWEEP_FAILED_GIVEUP = timedelta(days=7)


@celery.task(name="app.tasks.pipeline.pipeline_sweep")
def pipeline_sweep_task() -> None:
    """流水线自动补偿（每小时）：把卡住的公告按其所处阶段重新派发。

    覆盖两类：①中间状态停滞超 1 小时（worker 重启/任务丢失）；②failed 超 6 小时重试
    （LLM 欠费恢复后自动消化积压），失败超 7 天放弃避免永久坏数据空转。"""
    now = datetime.now(UTC)
    dispatch: list[tuple[str, int]] = []
    with session_scope() as session:
        stuck = session.scalars(
            select(Announcement)
            .where(
                Announcement.status.in_(
                    ("crawled", "cleaned", "attachments_parsed", "ai_extracted", "embedded")
                ),
                Announcement.updated_at < now - SWEEP_STUCK_AFTER,
            )
            .order_by(Announcement.updated_at)
            .limit(50)
        ).all()
        failed = session.scalars(
            select(Announcement)
            .where(
                Announcement.status == AnnouncementStatus.FAILED.value,
                Announcement.updated_at < now - SWEEP_FAILED_AFTER,
                Announcement.updated_at > now - SWEEP_FAILED_GIVEUP,
            )
            .order_by(Announcement.updated_at)
            .limit(20)
        ).all()
        for ann in stuck + failed:
            if ann.status == "crawled" or (ann.status == "failed" and not ann.clean_text):
                dispatch.append(("clean", ann.id))
            elif ann.status in ("cleaned", "attachments_parsed") or ann.status == "failed":
                dispatch.append(("extract", ann.id))
            else:  # ai_extracted / embedded：只差发布
                dispatch.append(("publish", ann.id))
    tasks = {"clean": fetch_and_clean_task, "extract": ai_extract_task, "publish": publish_task}
    for kind, ann_id in dispatch:
        tasks[kind].delay(ann_id)
    if dispatch:
        logger.info("流水线补偿：重派 %d 条（%s）", len(dispatch),
                    {k: sum(1 for x, _ in dispatch if x == k) for k in {x for x, _ in dispatch}})


@celery.task(name="app.tasks.pipeline.health_alert")
def health_alert_task() -> None:
    """健康告警（每 30 分钟）：LLM 连续失败 / 提取积压异常时站内信通知平台管理员，6 小时冷却。"""
    from app.core.ratelimit import acquire_cooldown, counter_get, note_get
    from app.models import Notification, User

    problems: list[str] = []
    failures = counter_get("llm_failures")
    if failures >= 5:
        last = note_get("llm_last_error") or ""
        problems.append(f"LLM 连续失败 {failures} 次（可能欠费或密钥失效）。最近报错：{last}")
    with session_scope() as session:
        backlog = session.scalar(
            select(func.count()).select_from(Announcement).where(
                Announcement.status.in_(("cleaned", "attachments_parsed")),
                Announcement.updated_at < datetime.now(UTC) - timedelta(hours=2),
            )
        )
        if backlog and backlog > 100:
            problems.append(f"待 AI 提取积压 {backlog} 条已超 2 小时，请检查 worker 与 LLM 状态")
        if not problems:
            return
        if not acquire_cooldown("health_alert", 6 * 3600):
            return
        admin_tenants = set(
            session.scalars(select(User.tenant_id).where(User.role == "platform_admin")).all()
        )
        for tid in admin_tenants:
            session.add(
                Notification(
                    tenant_id=tid, channel="web", title="【系统告警】流水线异常",
                    body="；\n".join(problems),
                )
            )
    logger.warning("系统健康告警已发送：%s", problems)


@celery.task(name="app.tasks.pipeline.daily_digest")
def daily_digest_task() -> None:
    with session_scope() as session:
        tenant_ids = session.scalars(select(Tenant.id).where(Tenant.enabled)).all()
        for tenant_id in tenant_ids:
            dispatch_daily_digest(session, tenant_id)
