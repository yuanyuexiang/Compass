"""公共层数据接口（公告/项目/统计）。数据本身租户无关，但访问需登录。"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.core.db import session_scope
from app.core.security import CurrentUser, CurrentUserDep
from app.matching.profiles import get_filter_regions, get_watched_source_ids, region_filter_clause
from app.models import (
    Announcement,
    CompanyProfile,
    MatchResult,
    Notification,
    Project,
    Source,
    SourceStatus,
    Subscription,
    Tenant,
    User,
)

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
    include_results: bool = False,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    current: CurrentUser = CurrentUserDep,
) -> dict:
    with session_scope() as session:
        # outer join Project：地区过滤需匹配结构化字段 region（与推荐/NL 搜索同源）
        stmt = select(Announcement).join(
            Project, Project.announcement_id == Announcement.id, isouter=True
        )
        # 默认隐藏中标/成交/废标等结果类公告（已无法投标，与推荐口径一致）；开关可放开看竞争情报
        if not include_results:
            stmt = stmt.where(Announcement.biddable.isnot(False))
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
        # 租户「关注的数据源」（订阅设置）：空 = 不限；与推荐 fan-out 口径一致
        if source_ids := get_watched_source_ids(session, current.tenant_id):
            stmt = stmt.where(Announcement.source_id.in_(source_ids))
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
    """工作台统计。流水线明细（by_status）是平台运营指标，仅平台管理员可见；
    租户看「可见公告数」——与商机查询同口径（画像地区 + 关注数据源）。"""
    with session_scope() as session:
        visible_stmt = (
            select(Announcement.id)
            .join(Project, Project.announcement_id == Announcement.id, isouter=True)
            .where(Announcement.biddable.isnot(False))  # 只数还能投的，与商机查询默认口径一致
        )
        if (
            clause := region_filter_clause(get_filter_regions(session, current.tenant_id))
        ) is not None:
            visible_stmt = visible_stmt.where(clause)
        if source_ids := get_watched_source_ids(session, current.tenant_id):
            visible_stmt = visible_stmt.where(Announcement.source_id.in_(source_ids))
        visible = session.scalar(select(func.count()).select_from(visible_stmt.subquery()))
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
        out = {
            "visible_announcements": visible,
            "tenant": {"today_recommended": today_recommended, "unread": unread},
        }
        if current.role == "platform_admin":
            pending_tenants = session.scalar(
                select(func.count()).select_from(Tenant).where(Tenant.status == "pending")
            )
            pending_sources = session.scalar(
                select(func.count()).select_from(Source).where(
                    Source.status == SourceStatus.PENDING.value
                )
            )
            active_sources = session.scalar(
                select(func.count()).select_from(Source).where(
                    Source.enabled, Source.status == SourceStatus.ACTIVE.value
                )
            )
            tenants_total = session.scalar(
                select(func.count()).select_from(Tenant).where(Tenant.is_platform.is_(False))
            )
            users_total = session.scalar(select(func.count()).select_from(User))
            out["by_status"] = dict(
                session.execute(
                    select(Announcement.status, func.count()).group_by(Announcement.status)
                ).all()
            )
            out["platform"] = {
                "pending_tenants": pending_tenants,
                "pending_sources": pending_sources,
                "active_sources": active_sources,
                "tenants_total": tenants_total,
                "users_total": users_total,
            }
        else:
            members_total = session.scalar(
                select(func.count()).select_from(User).where(User.tenant_id == current.tenant_id)
            )
            profile = session.scalar(
                select(CompanyProfile).where(CompanyProfile.tenant_id == current.tenant_id)
            )
            subscription = session.scalar(
                select(Subscription).where(Subscription.tenant_id == current.tenant_id)
            )
            profile_data = profile.data if profile else {}
            # 完整度只统计用户可填字段：name 强制为租户名恒有值、filter 是 dict 恒 truthy，
            # 直接计入会虚高——filter 按其内部 regions/min_budget 是否填过判定
            fields = [k for k in profile_data if k not in ("name", "filter")]
            filled = sum(1 for k in fields if profile_data.get(k))
            flt = profile_data.get("filter") or {}
            fields.append("filter")
            filled += 1 if (flt.get("regions") or flt.get("min_budget")) else 0
            out["tenant"] |= {
                "members_total": members_total,
                "profile_completeness": round(filled * 100 / max(len(fields), 1)),
                "subscribed_sources": len(subscription.source_ids or []) if subscription else 0,
                "source_scope_all": not bool(subscription and subscription.source_ids),
            }
        return out
