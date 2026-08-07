"""公共层流水线（tech-design.md §4）。

纯函数（run_*，可同步调用、可测试）+ Celery 薄包装（*_task）。
状态机：crawled → cleaned → attachments_parsed →（M2）ai_extracted → embedded → published
"""

import logging
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai import embeddings
from app.ai.extract import build_input, extract_project
from app.ai.profile_materials import run_material_extraction
from app.core import storage
from app.core.audit import record_event
from app.core.db import session_scope
from app.crawler.base import SourceAdapter, ensure_cst, get_adapter, url_fingerprint
from app.matching.engine import rule_filter, run_match, vector_similarity
from app.matching.profiles import tenant_watches_source
from app.models import (
    Announcement,
    AnnouncementStatus,
    Attachment,
    CompanyProfile,
    MatchResult,
    ProfileMaterial,
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

BEIJING_TZ = timezone(timedelta(hours=8))


def automatic_llm_allowed(now: datetime | None = None) -> bool:
    """自动 LLM 是否处于运行时间窗；传入时间可为任意时区，便于测试。"""
    from app.core.kv import AUTO_LLM_END_MINUTE, AUTO_LLM_START_MINUTE

    local = (now or datetime.now(BEIJING_TZ)).astimezone(BEIJING_TZ)
    minute = local.hour * 60 + local.minute
    if AUTO_LLM_START_MINUTE <= AUTO_LLM_END_MINUTE:
        return AUTO_LLM_START_MINUTE <= minute < AUTO_LLM_END_MINUTE
    return minute >= AUTO_LLM_START_MINUTE or minute < AUTO_LLM_END_MINUTE


def next_automatic_llm_start(now: datetime | None = None) -> datetime:
    """返回下一次自动 LLM 窗口起点（UTC），供跨越关窗时刻的任务安全延期。"""
    from app.core.kv import AUTO_LLM_START_MINUTE

    local = (now or datetime.now(BEIJING_TZ)).astimezone(BEIJING_TZ)
    start = local.replace(
        hour=AUTO_LLM_START_MINUTE // 60,
        minute=AUTO_LLM_START_MINUTE % 60,
        second=0,
        microsecond=0,
    )
    if local >= start:
        start += timedelta(days=1)
    return start.astimezone(UTC)


@celery.task(name="app.tasks.pipeline.profile_material_extract")
def profile_material_extract_task(material_id: int) -> None:
    """后台提取企业材料；失败状态保留供前端展示和人工重试。"""
    try:
        with session_scope() as session:
            material = session.get(ProfileMaterial, material_id)
            if material is None:
                return
            material.parse_status = "extracting"
            material.error = None
        with session_scope() as session:
            run_material_extraction(session, material_id)
    except Exception as exc:  # noqa: BLE001  需要把第三方 LLM 错误落到材料状态
        logger.exception("画像材料抽取失败 material=%s", material_id)
        with session_scope() as session:
            material = session.get(ProfileMaterial, material_id)
            if material is not None:
                material.parse_status = "extract_failed"
                material.error = str(exc)[:1000]


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
    """每分钟 tick：按管理员配置的间隔（system_settings）决定是否派发全量采集。

    原则：AI 能处理才采集——夜间关窗、LLM 连败、队列未消化完时一条都不采，
    积压从源头不形成（公告仍挂在源站列表页上，恢复后照常采到，不丢数据）。"""
    from app.core.kv import (
        DEFAULT_CRAWL_INTERVAL_MINUTES,
        KEY_CRAWL_INTERVAL,
        KEY_LAST_AUTO_CRAWL,
        get_setting,
        set_setting,
    )

    now = datetime.now(UTC)
    if not automatic_llm_allowed(now):
        return  # AI 停机时段不采集，采了也只能攒积压
    with session_scope() as session:
        interval = int(get_setting(session, KEY_CRAWL_INTERVAL, DEFAULT_CRAWL_INTERVAL_MINUTES))
        if not crawl_is_due(get_setting(session, KEY_LAST_AUTO_CRAWL), interval, now):
            return
        # 背压：AI 消化不动时不采新的（不记 last_auto_crawl，压力解除下个 tick 立即恢复）
        reason = auto_pipeline_backpressure(session, now)
        if reason:
            logger.info("自动采集暂停（%s），消化后自动恢复", reason)
            from app.core.ratelimit import acquire_cooldown

            if acquire_cooldown("evt_backpressure", 1800):  # 每次 tick 都触发，30 分钟记一条
                record_event(
                    session, "backpressure.pause", f"自动采集暂停：{reason}", level="warning"
                )
            return
        set_setting(session, KEY_LAST_AUTO_CRAWL, now.isoformat())
        source_ids = session.scalars(
            select(Source.id).where(Source.enabled, Source.status == SourceStatus.ACTIVE.value)
        ).all()
        record_event(
            session, "crawl.round", f"自动采集触发：间隔 {interval} 分钟，{len(source_ids)} 个源"
        )
    logger.info("自动采集触发（间隔 %d 分钟，%d 个源）", interval, len(source_ids))
    for sid in source_ids:
        crawl_source_task.delay(sid, True)


@celery.task(name="app.tasks.pipeline.crawl_all_sources")
def crawl_all_sources() -> None:
    """手动全量采集（不影响自动调度的计时）。"""
    with session_scope() as session:
        source_ids = session.scalars(
            select(Source.id).where(Source.enabled, Source.status == SourceStatus.ACTIVE.value)
        ).all()
    for sid in source_ids:
        crawl_source_task.delay(sid, False)


@celery.task(name="app.tasks.pipeline.crawl_source", max_retries=2, default_retry_delay=300)
def crawl_source_task(source_id: int, automatic: bool = False) -> None:
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None or not source.enabled or source.status != SourceStatus.ACTIVE.value:
            return
        new_ids = run_crawl_source(session, source)
        source.last_run_at = datetime.now(UTC)
    for ann_id in new_ids:
        fetch_and_clean_task.delay(ann_id, automatic)


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
def fetch_and_clean_task(announcement_id: int, automatic: bool = False) -> None:
    with session_scope() as session:
        run_fetch_and_clean(session, announcement_id)
    if not automatic or automatic_llm_allowed():
        ai_extract_task.delay(announcement_id, automatic)
    else:
        logger.info("夜间暂停自动 AI 提取，公告保留待处理 ann=%s", announcement_id)


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
def ai_extract_task(announcement_id: int, automatic: bool = False) -> None:
    if automatic and not automatic_llm_allowed():
        logger.info("自动 AI 提取已越过运行时间窗，留待白天处理 ann=%s", announcement_id)
        return
    try:
        with session_scope() as session:
            # 时效统一闸门：无论从哪条链路派发来，自动提取都不处理过期公告
            if automatic:
                ann = session.get(Announcement, announcement_id)
                if ann is not None and announcement_is_stale(ann, extract_deadline()):
                    ann.status = AnnouncementStatus.SKIPPED.value
                    ann.error = SKIP_STALE_NOTE
                    logger.info("超时效放弃自动 AI 提取 ann=%s", announcement_id)
                    return
            run_ai_extract(session, announcement_id)
    except Exception as exc:
        # run_ai_extract 内的状态修改会随异常事务回滚，必须用独立事务持久化失败现场。
        with session_scope() as session:
            ann = session.get(Announcement, announcement_id)
            if ann is not None:
                ann.status = AnnouncementStatus.FAILED.value
                ann.error = str(exc)[:2000]
        raise
    publish_task.delay(announcement_id, automatic)


@celery.task(name="app.tasks.pipeline.publish", max_retries=2, default_retry_delay=60)
def publish_task(announcement_id: int, automatic: bool = False) -> None:
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
        match_project_task.delay(project, tenant_id, automatic)


@celery.task(name="app.tasks.pipeline.match_project", max_retries=2, default_retry_delay=60)
def match_project_task(project_id: int, tenant_id: int, automatic: bool = False) -> None:
    if automatic and not automatic_llm_allowed():
        eta = next_automatic_llm_start()
        match_project_task.apply_async(args=(project_id, tenant_id, True), eta=eta)
        logger.info(
            "夜间暂停自动商机匹配，延期至 %s project=%s tenant=%s",
            eta.isoformat(),
            project_id,
            tenant_id,
        )
        return
    with session_scope() as session:
        match = run_match(session, project_id, tenant_id)
        if match is not None:
            dispatch_match(session, match)


REMATCH_WINDOW_DAYS = 7
REMATCH_LLM_LIMIT = 60


def select_rematch_candidates(
    session: Session, tenant_id: int, project_ids: list[int], limit: int = REMATCH_LLM_LIMIT
) -> list[int]:
    """零 Token 预筛画像重匹配候选：硬规则先过滤，再按已有结果和向量相关性排序。"""
    profile = session.scalar(select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id))
    if profile is None:
        return []
    existing_ids = set(
        session.scalars(
            select(MatchResult.project_id).where(
                MatchResult.tenant_id == tenant_id,
                MatchResult.project_id.in_(project_ids),
            )
        ).all()
    ) if project_ids else set()
    ranked: list[tuple[int, float, int]] = []
    for project_id in project_ids:
        project = session.get(Project, project_id)
        if project is None or not rule_filter(project, profile.data or {})[0]:
            continue
        similarity = vector_similarity(session, project, tenant_id)
        # 已产出过的推荐优先刷新；其余按向量相关性排序。无向量数据仍保留在候选尾部。
        ranked.append(
            (
                1 if project_id in existing_ids else 0,
                similarity if similarity is not None else -1.0,
                project_id,
            )
        )
    ranked.sort(reverse=True)
    return [project_id for _, _, project_id in ranked[:limit]]


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
        all_project_ids = list(session.scalars(stmt).all())
        project_ids = select_rematch_candidates(session, tenant_id, all_project_ids)
    done = 0
    for pid in project_ids:
        with session_scope() as session:
            if run_match(session, pid, tenant_id, force=True) is not None:
                done += 1
    logger.info(
        "画像重评估完成 tenant=%s 窗口=%d天 原始=%d 精排候选=%d 产出/更新=%d",
        tenant_id, REMATCH_WINDOW_DAYS, len(all_project_ids), len(project_ids), done,
    )
    with session_scope() as session:
        record_event(
            session, "profile.rematch",
            f"画像重评估完成：租户 {tenant_id}，"
            f"精排候选 {len(project_ids)} 条，产出/更新 {done} 条",
        )


SWEEP_STUCK_AFTER = timedelta(hours=1)
SWEEP_FAILED_AFTER = timedelta(hours=6)
SWEEP_FAILED_GIVEUP = timedelta(days=7)

SKIP_STALE_NOTE = "超过自动提取时效，已放弃（如需可手动重跑提取）"


def extract_deadline(now: datetime | None = None) -> datetime:
    """自动 AI 提取时效线：公告发布时间（缺失则按采集时间）早于该线的不再自动提取。

    按发布时间而非采集时间判定——新接入源一次性灌入的历史公告采集时间很新、
    发布时间很旧，正是最该整批放弃的场景。"""
    from app.core.kv import AUTO_EXTRACT_MAX_AGE_HOURS

    return (now or datetime.now(UTC)) - timedelta(hours=AUTO_EXTRACT_MAX_AGE_HOURS)


def announcement_stale_clause(deadline: datetime):
    """SQL 条件：公告超自动提取时效（发布时间缺失回退采集时间）。"""
    return func.coalesce(Announcement.publish_time, Announcement.created_at) < deadline


def announcement_is_stale(ann: Announcement, deadline: datetime) -> bool:
    return (ann.publish_time or ann.created_at) < deadline


def skip_stale_extract_backlog(session: Session, now: datetime | None = None) -> int:
    """把超时效仍未提取的公告批量标 skipped（纯 UPDATE 不烧 token，幂等）。"""
    result = session.execute(
        update(Announcement)
        .where(
            Announcement.status.in_(
                (
                    AnnouncementStatus.CLEANED.value,
                    AnnouncementStatus.ATTACHMENTS_PARSED.value,
                )
            ),
            announcement_stale_clause(extract_deadline(now)),
        )
        .values(status=AnnouncementStatus.SKIPPED.value, error=SKIP_STALE_NOTE)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def llm_streak_broken() -> bool:
    """LLM 是否处于连续失败流（欠费/密钥失效等）；任一调用成功即清零自愈。"""
    from app.core.kv import LLM_FAILURE_PAUSE_STREAK
    from app.core.ratelimit import counter_get

    return counter_get("llm_failures") >= LLM_FAILURE_PAUSE_STREAK


def extract_backlog_count(session: Session, now: datetime | None = None) -> int:
    """时效内待 AI 提取数量（超时效的会被自动放弃，不计入背压）。"""
    return (
        session.scalar(
            select(func.count())
            .select_from(Announcement)
            .where(
                Announcement.status.in_(
                    (
                        AnnouncementStatus.CLEANED.value,
                        AnnouncementStatus.ATTACHMENTS_PARSED.value,
                    )
                ),
                ~announcement_stale_clause(extract_deadline(now)),
            )
        )
        or 0
    )


def auto_pipeline_backpressure(session: Session, now: datetime | None = None) -> str | None:
    """自动流水线背压检查：AI 处理不动就别再采新的。返回暂停原因（None = 正常）。"""
    from app.core.kv import AUTO_CRAWL_MAX_PENDING

    if llm_streak_broken():
        return "LLM 连续失败中"
    pending = extract_backlog_count(session, now)
    if pending >= AUTO_CRAWL_MAX_PENDING:
        return f"待提取积压 {pending} 条已达阈值 {AUTO_CRAWL_MAX_PENDING}"
    return None


@celery.task(name="app.tasks.pipeline.ai_backlog_tick")
def ai_backlog_tick_task() -> None:
    """白天每五分钟限量恢复夜间积压；只接管时效内、已完成清洗/附件解析的公告。

    超时效的先批量标 skipped 放弃（放弃动作不分昼夜，避免积压触发夜间误告警）。"""
    from app.core.kv import AUTO_LLM_BACKLOG_BATCH
    from app.core.ratelimit import acquire_cooldown

    now = datetime.now(UTC)
    with session_scope() as session:
        stale = skip_stale_extract_backlog(session, now)
        if stale:
            record_event(session, "extract.skip_stale", f"放弃超时效待提取公告 {stale} 条")
    if stale:
        logger.info("放弃超时效待提取公告 %d 条（标 skipped）", stale)
    if not automatic_llm_allowed(now) or not acquire_cooldown("ai_backlog_tick", 240):
        return
    # LLM 连败时降为单条探针：不再成批送死，探针成功即清零计数、下个 tick 恢复满速
    probing = llm_streak_broken()
    batch = 1 if probing else AUTO_LLM_BACKLOG_BATCH
    with session_scope() as session:
        statuses = (
            (
                AnnouncementStatus.CLEANED.value,
                AnnouncementStatus.ATTACHMENTS_PARSED.value,
                AnnouncementStatus.FAILED.value,
            )
            if probing
            else (
                AnnouncementStatus.CLEANED.value,
                AnnouncementStatus.ATTACHMENTS_PARSED.value,
            )
        )
        announcement_ids = list(
            session.scalars(
                select(Announcement.id)
                .where(
                    Announcement.status.in_(statuses),
                    Announcement.clean_text.isnot(None),
                    ~announcement_stale_clause(extract_deadline(now)),
                )
                .order_by(Announcement.updated_at)
                .limit(batch)
            ).all()
        )
    for announcement_id in announcement_ids:
        ai_extract_task.delay(announcement_id, True)
    if announcement_ids:
        if batch == 1:
            logger.info("LLM 连续失败中，仅派发探针公告 ann=%s", announcement_ids[0])
            from app.core.ratelimit import acquire_cooldown

            if acquire_cooldown("evt_llm_probe", 1800):
                with session_scope() as session:
                    record_event(
                        session, "llm.probe",
                        "LLM 连续失败，暂停批量派发，仅以单条探针试探恢复", level="warning",
                    )
        else:
            logger.info("白天恢复待 AI 提取公告 %d 条", len(announcement_ids))


@celery.task(name="app.tasks.pipeline.pipeline_sweep")
def pipeline_sweep_task() -> None:
    """流水线自动补偿（每小时）：把卡住的公告按其所处阶段重新派发。

    覆盖两类：①中间状态停滞超 1 小时（worker 重启/任务丢失）；②failed 超 6 小时重试
    （LLM 欠费恢复后自动消化积压），失败超 7 天放弃避免永久坏数据空转。"""
    now = datetime.now(UTC)
    # 时间窗外或 LLM 连败中都不重派提取（连败恢复靠 ai_backlog_tick 的探针）
    llm_allowed = automatic_llm_allowed(now) and not llm_streak_broken()
    deadline = extract_deadline(now)
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
                # 超时效不再自动重试提取（含 failed 重试），直接放弃省 token
                if announcement_is_stale(ann, deadline):
                    ann.status = AnnouncementStatus.SKIPPED.value
                    ann.error = SKIP_STALE_NOTE
                    continue
                if not llm_allowed:
                    continue
                dispatch.append(("extract", ann.id))
            else:  # ai_extracted / embedded：只差发布
                dispatch.append(("publish", ann.id))
        if dispatch:
            counts = {k: sum(1 for x, _ in dispatch if x == k) for k in {x for x, _ in dispatch}}
            record_event(session, "pipeline.sweep", f"流水线补偿重派 {len(dispatch)} 条：{counts}")
    tasks = {"clean": fetch_and_clean_task, "extract": ai_extract_task, "publish": publish_task}
    for kind, ann_id in dispatch:
        tasks[kind].delay(ann_id, True)
    if dispatch:
        logger.info("流水线补偿：重派 %d 条（%s）", len(dispatch),
                    {k: sum(1 for x, _ in dispatch if x == k) for k in {x for x, _ in dispatch}})


@celery.task(name="app.tasks.pipeline.health_alert")
def health_alert_task() -> None:
    """健康告警（每 30 分钟）：LLM 连续失败 / 提取积压异常时站内信通知平台管理员，6 小时冷却。"""
    from app.core.kv import LLM_FAILURE_PAUSE_STREAK
    from app.core.ratelimit import acquire_cooldown, counter_get, note_get
    from app.models import Notification, User

    problems: list[str] = []
    failures = counter_get("llm_failures")
    if failures >= LLM_FAILURE_PAUSE_STREAK:
        last = note_get("llm_last_error") or ""
        problems.append(f"LLM 连续失败 {failures} 次（可能欠费或密钥失效）。最近报错：{last}")
    with session_scope() as session:
        # 排队本身是限速消化的常态（不报）；等超 24 小时说明消化已停摆（时间窗每天
        # 15 小时、吞吐 3600 条/天，正常情况不可能等这么久），才是真故障。
        backlog = session.scalar(
            select(func.count()).select_from(Announcement).where(
                Announcement.status.in_(("cleaned", "attachments_parsed")),
                Announcement.updated_at < datetime.now(UTC) - timedelta(hours=24),
            )
        )
        if backlog and backlog > 10:
            problems.append(
                f"{backlog} 条公告等待 AI 提取超 24 小时，消化可能已停摆，"
                "请检查 beat/worker 与 LLM 状态"
            )
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
        record_event(session, "health.alert", "；".join(problems), level="error")
    logger.warning("系统健康告警已发送：%s", problems)


@celery.task(name="app.tasks.pipeline.daily_digest")
def daily_digest_task() -> None:
    with session_scope() as session:
        tenant_ids = session.scalars(select(Tenant.id).where(Tenant.enabled)).all()
        for tenant_id in tenant_ids:
            dispatch_daily_digest(session, tenant_id)


@celery.task(name="app.tasks.pipeline.logs_cleanup")
def logs_cleanup_task() -> None:
    """每日清理过期日志：操作日志留 AUDIT_LOG_RETENTION_DAYS 天，运行日志留 30 天。"""
    from sqlalchemy import delete as sa_delete

    from app.core.kv import AUDIT_LOG_RETENTION_DAYS, SYSTEM_EVENT_RETENTION_DAYS
    from app.models import AuditLog, SystemEvent

    now = datetime.now(UTC)
    with session_scope() as session:
        audits = session.execute(
            sa_delete(AuditLog).where(
                AuditLog.created_at < now - timedelta(days=AUDIT_LOG_RETENTION_DAYS)
            )
        ).rowcount
        events = session.execute(
            sa_delete(SystemEvent).where(
                SystemEvent.created_at < now - timedelta(days=SYSTEM_EVENT_RETENTION_DAYS)
            )
        ).rowcount
    if audits or events:
        logger.info("日志清理：操作日志 %d 条、运行日志 %d 条", audits, events)
