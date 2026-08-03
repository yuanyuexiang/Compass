"""一次性放弃当前待 AI 提取积压（cleaned/attachments_parsed → skipped）。

用于清掉历史性大积压（如一次性接入新源灌入上万条旧公告），避免自动流水线
持续烧 token 消化没有商机价值的过期公告。标 skipped 后不再派发、不计积压告警，
原始数据保留，需要时可手动重跑提取。

用法：
  uv run python scripts/skip_extract_backlog.py            # 放弃全部当前积压
  uv run python scripts/skip_extract_backlog.py --keep-hours 48
      # 保留最近 48 小时内采集的（仍走自动提取），只放弃更早的
生产（docker）：docker compose exec api python scripts/skip_extract_backlog.py
"""

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.db import session_scope
from app.models import Announcement
from app.models.public import AnnouncementStatus
from app.tasks.pipeline import SKIP_STALE_NOTE, announcement_stale_clause

PENDING = (
    AnnouncementStatus.CLEANED.value,
    AnnouncementStatus.ATTACHMENTS_PARSED.value,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-hours",
        type=float,
        default=0,
        help="保留最近 N 小时内发布（缺失按采集时间）的公告继续自动提取（默认 0 = 全部放弃）",
    )
    args = parser.parse_args()

    stmt = (
        update(Announcement)
        .where(Announcement.status.in_(PENDING))
        .values(status=AnnouncementStatus.SKIPPED.value, error=SKIP_STALE_NOTE)
        .execution_options(synchronize_session=False)
    )
    if args.keep_hours > 0:
        cutoff = datetime.now(UTC) - timedelta(hours=args.keep_hours)
        stmt = stmt.where(announcement_stale_clause(cutoff))

    with session_scope() as session:
        count = session.execute(stmt).rowcount or 0
    print(f"skipped {count} pending announcements")


if __name__ == "__main__":
    main()
