from datetime import UTC, datetime

import pytest

from app.api.routes.sources import ScheduleIn
from app.tasks.pipeline import automatic_llm_allowed, crawl_is_due, next_automatic_llm_start

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


def test_next_automatic_llm_start_is_next_morning():
    from app.tasks.pipeline import BEIJING_TZ

    now = datetime(2026, 7, 8, 23, 0, tzinfo=BEIJING_TZ)
    assert next_automatic_llm_start(now) == datetime(2026, 7, 8, 23, 30, tzinfo=UTC)


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
