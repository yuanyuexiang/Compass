"""M2 演练脚本：对库中已清洗的真实公告跑 AI 提取，人工检验质量。

用法（backend/ 目录下，需 .env 配好 DEEPSEEK_API_KEY）：
    uv run python scripts/dev_extract.py --limit 3
"""

import argparse

from sqlalchemy import select


def main(limit: int) -> None:
    from app.core.db import session_scope
    from app.models import Announcement, AnnouncementStatus
    from app.tasks.pipeline import run_ai_extract

    with session_scope() as session:
        ids = session.scalars(
            select(Announcement.id)
            .where(Announcement.status == AnnouncementStatus.ATTACHMENTS_PARSED.value)
            .order_by(Announcement.id)
            .limit(limit)
        ).all()
    if not ids:
        print("没有待提取的公告（status=attachments_parsed）")
        return

    for ann_id in ids:
        with session_scope() as session:
            ann = session.get(Announcement, ann_id)
            print(f"\n{'=' * 70}\n#{ann.id} {ann.title}")
            project = run_ai_extract(session, ann_id)
            for name, f in project.fields.items():
                mark = "⚠" if (f["confidence"] or 0) < 0.7 else " "
                print(f" {mark} {name:18s} = {f['value']!r:60s} conf={f['confidence']}")
                if f["evidence"]:
                    print(f"     依据: {f['evidence'][:60]}")
            print(f"   分类: {project.category}")
            print(f"   摘要: {project.summary}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    main(parser.parse_args().limit)
