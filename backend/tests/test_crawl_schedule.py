from datetime import UTC, datetime

import pytest

from app.api.routes.sources import ScheduleIn
from app.tasks.pipeline import (
    auto_window_minutes_between,
    automatic_llm_allowed,
    crawl_is_due,
    next_automatic_llm_start,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


def test_due_when_never_run():
    assert crawl_is_due(None, 30, NOW) is True


def test_not_due_within_interval():
    last = datetime(2026, 7, 8, 11, 45, 0, tzinfo=UTC).isoformat()
    assert crawl_is_due(last, 30, NOW) is False


def test_due_at_or_after_interval():
    last = datetime(2026, 7, 8, 11, 30, 0, tzinfo=UTC).isoformat()
    assert crawl_is_due(last, 30, NOW) is True
    assert crawl_is_due(last, 15, NOW) is True


def test_interval_change_takes_effect_immediately():
    # 20 分钟前跑过：间隔 30 → 未到点；管理员改成 15 → 立即判定到点
    last = datetime(2026, 7, 8, 11, 40, 0, tzinfo=UTC).isoformat()
    assert crawl_is_due(last, 30, NOW) is False
    assert crawl_is_due(last, 15, NOW) is True


def test_schedule_input_bounds():
    with pytest.raises(ValueError):
        ScheduleIn(interval_minutes=4)  # 低于 5 分钟礼貌下限
    with pytest.raises(ValueError):
        ScheduleIn(interval_minutes=721)
    assert ScheduleIn(interval_minutes=30).interval_minutes == 30


@pytest.mark.parametrize(
    ("hour", "minute", "allowed"),
    [(7, 29, False), (7, 30, True), (12, 0, True), (22, 29, True), (22, 30, False)],
)
def test_automatic_llm_beijing_window(hour, minute, allowed):
    from app.tasks.pipeline import BEIJING_TZ

    now = datetime(2026, 7, 8, hour, minute, tzinfo=BEIJING_TZ)
    assert automatic_llm_allowed(now) is allowed


def test_auto_window_minutes_freezes_overnight():
    """夜间关窗时段不计入调度间隔——健康面板凌晨不得误报停摆。

    实测复盘：当晚最后一轮 21:41（北京），凌晨 01:15 看工作台，裸时间差 214 分钟
    已超 3×60 阈值挂出「采集疑似停摆」，而窗口内时间其实只走了 49 分钟。
    """
    last_round = datetime(2026, 8, 8, 13, 41, 0, tzinfo=UTC)  # 北京 21:41
    midnight_check = datetime(2026, 8, 8, 17, 15, 0, tzinfo=UTC)  # 北京次日 01:15
    assert auto_window_minutes_between(last_round, midnight_check) == pytest.approx(49)


def test_auto_window_minutes_resumes_next_morning():
    # 北京 21:41 → 次日 08:00：昨晚尾巴 49 分钟 + 今晨开窗后 30 分钟
    last_round = datetime(2026, 8, 8, 13, 41, 0, tzinfo=UTC)
    next_morning = datetime(2026, 8, 9, 0, 0, 0, tzinfo=UTC)  # 北京 08:00
    assert auto_window_minutes_between(last_round, next_morning) == pytest.approx(79)


def test_auto_window_minutes_zero_when_fully_closed():
    start = datetime(2026, 8, 8, 15, 0, 0, tzinfo=UTC)  # 北京 23:00
    end = datetime(2026, 8, 8, 22, 0, 0, tzinfo=UTC)  # 北京次日 06:00
    assert auto_window_minutes_between(start, end) == 0.0
    assert auto_window_minutes_between(end, start) == 0.0  # 逆序防御


def test_auto_window_minutes_plain_gap_inside_window():
    start = datetime(2026, 8, 8, 2, 0, 0, tzinfo=UTC)  # 北京 10:00
    end = datetime(2026, 8, 8, 4, 0, 0, tzinfo=UTC)  # 北京 12:00
    assert auto_window_minutes_between(start, end) == pytest.approx(120)


def test_next_automatic_llm_start_is_next_morning():
    from app.tasks.pipeline import BEIJING_TZ

    now = datetime(2026, 7, 8, 23, 0, tzinfo=BEIJING_TZ)
    assert next_automatic_llm_start(now) == datetime(2026, 7, 8, 23, 30, tzinfo=UTC)


def test_extract_deadline_is_max_age_before_now():
    from datetime import timedelta

    from app.core.kv import AUTO_EXTRACT_MAX_AGE_HOURS
    from app.tasks.pipeline import extract_deadline

    assert extract_deadline(NOW) == NOW - timedelta(hours=AUTO_EXTRACT_MAX_AGE_HOURS)


def test_skip_stale_extract_backlog():
    """超时效（按发布时间，缺失回退采集时间）的待提取公告批量标 skipped。"""
    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import Announcement
    from app.models.public import AnnouncementStatus
    from app.tasks.pipeline import SKIP_STALE_NOTE, skip_stale_extract_backlog

    engine = create_engine("sqlite://")
    Announcement.__table__.create(engine)
    with Session(engine) as session:
        ids = iter(range(1, 100))

        def ann(fp, status, crawled_hours_ago, published_hours_ago=None):
            # SQLite 下 BigInteger 主键不自增，显式给 id
            return Announcement(
                id=next(ids), source_id=1, url=f"http://x/{fp}", fingerprint=fp,
                title=fp, status=status,
                created_at=NOW - timedelta(hours=crawled_hours_ago),
                publish_time=(
                    NOW - timedelta(hours=published_hours_ago)
                    if published_hours_ago is not None
                    else None
                ),
            )

        fresh = ann("fresh", AnnouncementStatus.CLEANED.value, 1, 3)
        # 新源灌入的历史公告：昨天才采集，但发布已 10 天 → 必须放弃
        dumped = ann("dumped", AnnouncementStatus.CLEANED.value, 20, 240)
        stale_no_pub = ann("stale1", AnnouncementStatus.CLEANED.value, 72)
        stale_parsed = ann("stale2", AnnouncementStatus.ATTACHMENTS_PARSED.value, 100, 100)
        published_old = ann("pub", AnnouncementStatus.PUBLISHED.value, 100, 100)
        session.add_all([fresh, dumped, stale_no_pub, stale_parsed, published_old])
        session.commit()

        assert skip_stale_extract_backlog(session, NOW) == 3
        session.commit()
        session.expire_all()
        assert fresh.status == AnnouncementStatus.CLEANED.value
        assert dumped.status == AnnouncementStatus.SKIPPED.value
        assert dumped.error == SKIP_STALE_NOTE
        assert stale_no_pub.status == AnnouncementStatus.SKIPPED.value
        assert stale_parsed.status == AnnouncementStatus.SKIPPED.value
        assert published_old.status == AnnouncementStatus.PUBLISHED.value
        # 幂等：再跑一遍无新增
        assert skip_stale_extract_backlog(session, NOW) == 0


def test_auto_pipeline_backpressure(monkeypatch):
    """AI 处理不动（积压达阈值 / LLM 连败）时返回暂停原因，正常时 None。"""
    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import Announcement
    from app.models.public import AnnouncementStatus
    from app.tasks import pipeline

    engine = create_engine("sqlite://")
    Announcement.__table__.create(engine)
    with Session(engine) as session:
        # 空库、LLM 正常 → 不背压
        monkeypatch.setattr(pipeline, "llm_streak_broken", lambda: False)
        assert pipeline.auto_pipeline_backpressure(session, NOW) is None

        # LLM 连败 → 立即背压（不看积压量）
        monkeypatch.setattr(pipeline, "llm_streak_broken", lambda: True)
        assert "LLM" in pipeline.auto_pipeline_backpressure(session, NOW)
        monkeypatch.setattr(pipeline, "llm_streak_broken", lambda: False)

        # 时效内积压达到阈值 → 背压；超时效的不计入
        monkeypatch.setattr("app.core.kv.AUTO_CRAWL_MAX_PENDING", 2)
        session.add_all(
            Announcement(
                id=i, source_id=1, url=f"http://x/{i}", fingerprint=f"f{i}",
                title=f"t{i}", status=AnnouncementStatus.CLEANED.value,
                created_at=NOW - timedelta(hours=1),
            )
            for i in range(1, 3)
        )
        session.add(
            Announcement(
                id=99, source_id=1, url="http://x/old", fingerprint="fold",
                title="old", status=AnnouncementStatus.CLEANED.value,
                created_at=NOW - timedelta(hours=1),
                publish_time=NOW - timedelta(hours=240),  # 超时效，不计入背压
            )
        )
        session.commit()
        assert pipeline.extract_backlog_count(session, NOW) == 2
        reason = pipeline.auto_pipeline_backpressure(session, NOW)
        assert reason is not None and "积压" in reason


def test_announcement_is_stale_prefers_publish_time():
    from datetime import timedelta
    from types import SimpleNamespace

    from app.tasks.pipeline import announcement_is_stale

    deadline = NOW - timedelta(hours=48)
    # 采集新、发布旧 → 过期；采集旧、发布新 → 未过期；无发布时间按采集时间
    old_pub = SimpleNamespace(publish_time=NOW - timedelta(hours=240),
                              created_at=NOW - timedelta(hours=1))
    new_pub = SimpleNamespace(publish_time=NOW - timedelta(hours=1),
                              created_at=NOW - timedelta(hours=240))
    no_pub = SimpleNamespace(publish_time=None, created_at=NOW - timedelta(hours=72))
    assert announcement_is_stale(old_pub, deadline) is True
    assert announcement_is_stale(new_pub, deadline) is False
    assert announcement_is_stale(no_pub, deadline) is True


def test_ai_extract_task_persists_failure_in_separate_transaction(monkeypatch):
    """提取异常不能随主事务回滚而丢失公告失败状态和错误现场。"""
    from contextlib import contextmanager

    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import Announcement
    from app.models.public import AnnouncementStatus
    from app.tasks import pipeline

    engine = create_engine("sqlite://")
    Announcement.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            Announcement(
                id=701,
                source_id=1,
                url="http://x/701",
                fingerprint="f701",
                title="probe",
                clean_text="body",
                status=AnnouncementStatus.ATTACHMENTS_PARSED.value,
                created_at=NOW,
            )
        )
        session.commit()

    @contextmanager
    def fake_scope():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(pipeline, "session_scope", fake_scope)
    monkeypatch.setattr(
        pipeline,
        "run_ai_extract",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        pipeline.ai_extract_task.run(701, False)

    with Session(engine) as session:
        announcement = session.get(Announcement, 701)
        assert announcement.status == AnnouncementStatus.FAILED.value
        assert announcement.error == "provider unavailable"


def test_fetch_and_clean_task_persists_failure_and_records_event(monkeypatch):
    """清洗异常不能无声回滚卡回 crawled（实测 9 条被 sweep 每小时空转重派两天）：
    独立事务落 failed+error，并采样记一条运行日志让原因自己浮上来。"""
    from contextlib import contextmanager

    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import Announcement
    from app.models.public import AnnouncementStatus
    from app.tasks import pipeline

    engine = create_engine("sqlite://")
    Announcement.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            Announcement(
                id=801, source_id=1, url="http://x/801", fingerprint="f801",
                title="probe", status=AnnouncementStatus.CRAWLED.value, created_at=NOW,
            )
        )
        session.commit()

    @contextmanager
    def fake_scope():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    events = []
    monkeypatch.setattr(pipeline, "session_scope", fake_scope)
    monkeypatch.setattr(
        pipeline,
        "run_fetch_and_clean",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("detail page 404")),
    )
    monkeypatch.setattr(
        pipeline, "record_event", lambda _s, event, detail, **kw: events.append((event, detail))
    )
    monkeypatch.setattr("app.core.ratelimit.acquire_cooldown", lambda *_a, **_k: True)

    with pytest.raises(RuntimeError, match="detail page 404"):
        pipeline.fetch_and_clean_task.run(801, False)

    with Session(engine) as session:
        announcement = session.get(Announcement, 801)
        assert announcement.status == AnnouncementStatus.FAILED.value
        assert announcement.error == "detail page 404"
    assert events and events[0][0] == "clean.failure" and "detail page 404" in events[0][1]


def test_sweep_gives_up_stale_clean_loop(monkeypatch):
    """sweep 熔断：清洗通道的卡死公告超时效后标 skipped（保留此前错误现场），
    时效内的照常重派，不再无限空转。"""
    from contextlib import contextmanager
    from datetime import timedelta
    from types import SimpleNamespace

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import Announcement
    from app.models.public import AnnouncementStatus
    from app.tasks import pipeline

    engine = create_engine("sqlite://")
    Announcement.__table__.create(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        # 卡死两天的：采集 72h 前（无发布时间按采集时间判过期），带此前清洗错误
        session.add(
            Announcement(
                id=901, source_id=1, url="http://x/901", fingerprint="f901",
                title="stuck", status=AnnouncementStatus.CRAWLED.value,
                created_at=now - timedelta(hours=72),
                updated_at=now - timedelta(hours=72), error="boom",
            )
        )
        # 时效内、停滞超 1 小时的：应正常重派清洗
        session.add(
            Announcement(
                id=902, source_id=1, url="http://x/902", fingerprint="f902",
                title="recent", status=AnnouncementStatus.CRAWLED.value,
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
            )
        )
        session.commit()

    @contextmanager
    def fake_scope():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    events, dispatched = [], []
    monkeypatch.setattr(pipeline, "session_scope", fake_scope)
    monkeypatch.setattr(
        pipeline, "record_event", lambda _s, event, detail, **kw: events.append((event, detail))
    )
    monkeypatch.setattr(
        pipeline, "fetch_and_clean_task",
        SimpleNamespace(delay=lambda ann_id, auto: dispatched.append(ann_id)),
    )

    pipeline.pipeline_sweep_task.run()

    with Session(engine) as session:
        stuck = session.get(Announcement, 901)
        assert stuck.status == AnnouncementStatus.SKIPPED.value
        assert pipeline.SKIP_STALE_NOTE in stuck.error and "boom" in stuck.error
        assert session.get(Announcement, 902).status == AnnouncementStatus.CRAWLED.value
    assert dispatched == [902]
    assert any(e == "extract.skip_stale" and "1 条" in d for e, d in events)


def test_ensure_cst():
    """采集解析出的 naive 北京时间入库前补东八区；已带时区/空值原样返回。"""
    from datetime import datetime, timedelta

    from app.crawler.base import CST, ensure_cst

    naive = datetime(2026, 7, 28, 21, 18)
    aware = ensure_cst(naive)
    assert aware.tzinfo == CST
    # 北京 21:18 == UTC 13:18
    assert aware.astimezone(UTC).hour == 13
    already = datetime(2026, 7, 28, 13, 18, tzinfo=UTC)
    assert ensure_cst(already) is already
    assert ensure_cst(None) is None
    assert CST.utcoffset(None) == timedelta(hours=8)
