from datetime import UTC, datetime

import pytest

from app.api.routes.sources import ScheduleIn
from app.tasks.pipeline import crawl_is_due

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
