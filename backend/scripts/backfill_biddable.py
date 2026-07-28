"""存量公告回填可投标判定（announcements.biddable）。

幂等：只处理 biddable IS NULL 的行，部署脚本每次跑一遍无副作用。
用法：uv run python scripts/backfill_biddable.py
"""

from sqlalchemy import select

from app.core.db import session_scope
from app.models import Announcement
from app.opportunity import is_biddable

BATCH = 1000


def main() -> None:
    total = 0
    while True:
        with session_scope() as session:
            rows = session.scalars(
                select(Announcement).where(Announcement.biddable.is_(None)).limit(BATCH)
            ).all()
            if not rows:
                break
            for ann in rows:
                ann.biddable = is_biddable(ann.ann_type, ann.title)
            total += len(rows)
    print(f"backfilled biddable for {total} announcements")


if __name__ == "__main__":
    main()
