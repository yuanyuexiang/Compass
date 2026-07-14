"""公共层数据接口（公告/项目/统计）。数据本身租户无关，但访问需登录。"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.core.db import session_scope
from app.core.security import CurrentUser, CurrentUserDep
from app.matching.profiles import get_filter_regions, region_filter_clause
from app.models import Announcement, MatchResult, Notification, Project

router = APIRouter(prefix="/api")


def announcement_out(a: Announcement) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "url": a.url,
        "ann_type": a.ann_type,
        "region": a.region,
        "buyer": a.buyer,
        "publish_time": a.publish_time,
        "status": a.status,
    }


@router.get("/announcements")
def list_announcements(
    keyword: str | None = None,
    region: str | None = None,
    status: str | None = None,
    all_regions: bool = False,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    current: CurrentUser = CurrentUserDep,
) -> dict:
    with session_scope() as session:
        # outer join Project：地区过滤需匹配结构化字段 region（与推荐/NL 搜索同源）
        stmt = select(Announcement).join(
            Project, Project.announcement_id == Announcement.id, isouter=True
        )
        if keyword:
            stmt = stmt.where(Announcement.title.ilike(f"%{keyword}%"))
        # 地区口径：显式地区参数优先；否则默认按画像「仅关注地区」；all_regions=True 时不限制
        if region:
            active_regions = [region]
        elif not all_regions:
            active_regions = get_filter_regions(session, current.tenant_id)
        else:
            active_regions = []
        if (clause := region_filter_clause(active_regions)) is not None:
            stmt = stmt.where(clause)
        if status:
            stmt = stmt.where(Announcement.status == status)
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(
            stmt.order_by(Announcement.publish_time.desc().nullslast()).limit(limit).offset(offset)
        ).all()
        return {
            "items": [announcement_out(a) for a in rows],
            "total": total,
            "region_scope": active_regions,
        }


@router.get("/projects/{announcement_id}")
def project_detail(announcement_id: int, current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        ann = session.get(Announcement, announcement_id)
        if ann is None:
            raise HTTPException(status_code=404, detail="公告不存在")
        project = session.scalar(select(Project).where(Project.announcement_id == announcement_id))
        return {
            "announcement": announcement_out(ann) | {"clean_text": ann.clean_text},
            "project": {
                "fields": project.fields,
                "category": project.category,
                "summary": project.summary,
            }
            if project
            else None,
            "attachments": [
                {"filename": a.filename, "status": a.status, "needs_ocr": a.needs_ocr}
                for a in ann.attachments
            ],
        }


@router.get("/stats")
def stats(current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        by_status = dict(
            session.execute(
                select(Announcement.status, func.count()).group_by(Announcement.status)
            ).all()
        )
        today_recommended = session.scalar(
            select(func.count())
            .select_from(MatchResult)
            .where(
                MatchResult.tenant_id == current.tenant_id,
                MatchResult.created_at >= func.current_date(),
            )
        )
        unread = session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.tenant_id == current.tenant_id,
                Notification.channel == "web",
                Notification.read.is_(False),
            )
        )
        return {
            "by_status": by_status,
            "tenant": {"today_recommended": today_recommended, "unread": unread},
        }


