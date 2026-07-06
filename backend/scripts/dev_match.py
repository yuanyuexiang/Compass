"""M3 演练：发布所有已提取公告 → 对种子租户跑三级漏斗匹配 → 触发即时通知。

用法：uv run python scripts/dev_match.py
"""

from sqlalchemy import select

from app.core.db import session_scope
from app.matching.engine import run_match
from app.models import Announcement, AnnouncementStatus, Project, Tenant
from app.notify.dispatcher import dispatch_match
from app.tasks.pipeline import run_embed_and_publish


def main() -> None:
    with session_scope() as session:
        ann_ids = session.scalars(
            select(Announcement.id).where(
                Announcement.status == AnnouncementStatus.AI_EXTRACTED.value
            )
        ).all()
        for ann_id in ann_ids:
            run_embed_and_publish(session, ann_id)
        print(f"发布公告 {len(ann_ids)} 条")
        tenant = session.scalar(select(Tenant).order_by(Tenant.id))
        project_ids = session.scalars(select(Project.id).order_by(Project.id)).all()

    print(f"租户 #{tenant.id} {tenant.name} × {len(project_ids)} 个项目：\n")
    for pid in project_ids:
        with session_scope() as session:
            project = session.get(Project, pid)
            ann = session.get(Announcement, project.announcement_id)
            match = run_match(session, pid, tenant.id)
            if match is None:
                print(f"  ✗ 被漏斗过滤   {ann.title[:38]}")
                continue
            dispatch_match(session, match)
            risks = sum(1 for r in (match.risks or {}).values() if r.get("hit"))
            print(
                f"  {'★' * match.star:<6} {match.match_score:>3.0f}分 {match.advice}"
                f" 风险{risks}项  {ann.title[:38]}"
            )


if __name__ == "__main__":
    main()
