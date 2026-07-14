"""租户层接口：推荐、跟进、画像、订阅、通知、NL 搜索。全部按 tenant_id 强制隔离。"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.nl_search import parse_query
from app.core.db import session_scope
from app.core.security import CurrentUser, CurrentUserDep
from app.matching.engine import parse_budget_yuan
from app.matching.profiles import get_filter_regions, region_filter_clause, upsert_profile
from app.models import (
    Announcement,
    CompanyProfile,
    MatchResult,
    Notification,
    Project,
    Subscription,
)

router = APIRouter(prefix="/api")

FOLLOW_STATUSES = ("待看", "跟进中", "放弃", "已投标")


@router.get("/recommendations")
def recommendations(
    min_star: int = 1,
    limit: int = Query(default=50, le=200),
    current: CurrentUser = CurrentUserDep,
) -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(MatchResult, Project, Announcement)
            .join(Project, MatchResult.project_id == Project.id)
            .join(Announcement, Project.announcement_id == Announcement.id)
            .where(MatchResult.tenant_id == current.tenant_id, MatchResult.star >= min_star)
            .order_by(MatchResult.star.desc(), MatchResult.match_score.desc())
            .limit(limit)
        ).all()
        out = []
        for match, project, ann in rows:
            fields = {k: (v or {}).get("value") for k, v in (project.fields or {}).items()}
            out.append(
                {
                    "id": match.id,
                    "project_id": project.id,
                    "announcement_id": ann.id,
                    "title": ann.title,
                    "url": ann.url,
                    "region": fields.get("region") or ann.region,
                    "budget": fields.get("budget"),
                    "deadline": fields.get("bid_deadline"),
                    "star": match.star,
                    "match_score": match.match_score,
                    "advice": match.advice,
                    "reasons": match.reasons,
                    "risks": match.risks,
                    "summary": project.summary,
                    "follow_status": match.follow_status,
                    "created_at": match.created_at,
                }
            )
        return out


class FollowIn(BaseModel):
    status: str


@router.post("/follow/{match_id}")
def follow(match_id: int, body: FollowIn, current: CurrentUser = CurrentUserDep) -> dict:
    if body.status not in FOLLOW_STATUSES:
        raise HTTPException(status_code=422, detail=f"状态须为 {FOLLOW_STATUSES}")
    with session_scope() as session:
        match = session.get(MatchResult, match_id)
        if match is None or match.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="记录不存在")
        match.follow_status = body.status
        return {"ok": True}


EMPTY_PROFILE = {
    "name": "", "description": "", "products": [], "services": [], "industries": [],
    "regions": [], "certifications": [], "brands": [], "cases_text": "",
    "filter": {"regions": [], "min_budget": None},
}


@router.get("/profile")
def get_profile(current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        profile = session.scalar(
            select(CompanyProfile).where(CompanyProfile.tenant_id == current.tenant_id)
        )
        return EMPTY_PROFILE | (profile.data if profile else {})


@router.put("/profile")
def put_profile(body: dict, current: CurrentUser = CurrentUserDep) -> dict:
    data = {k: body.get(k, v) for k, v in EMPTY_PROFILE.items()}
    with session_scope() as session:
        upsert_profile(session, current.tenant_id, data)
        return {"ok": True}


DEFAULT_CHANNELS = {
    "email": {"enabled": False, "address": ""},
    "wecom": {"enabled": False, "webhook": ""},
    "dingtalk": {"enabled": False, "webhook": ""},
    "feishu": {"enabled": False, "webhook": ""},
}


@router.get("/subscriptions")
def get_subscriptions(current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        sub = session.scalar(
            select(Subscription).where(Subscription.tenant_id == current.tenant_id)
        )
        if sub is None:
            return {
                "min_star": 4, "immediate": True, "daily_digest": True,
                "channels": DEFAULT_CHANNELS,
            }
        return {
            "min_star": sub.min_star,
            "immediate": sub.immediate,
            "daily_digest": sub.daily_digest,
            "channels": DEFAULT_CHANNELS | (sub.channels or {}),
        }


@router.put("/subscriptions")
def put_subscriptions(body: dict, current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        sub = session.scalar(
            select(Subscription).where(Subscription.tenant_id == current.tenant_id)
        )
        if sub is None:
            sub = Subscription(tenant_id=current.tenant_id)
            session.add(sub)
        sub.min_star = int(body.get("min_star", 4))
        sub.immediate = bool(body.get("immediate", True))
        sub.daily_digest = bool(body.get("daily_digest", True))
        sub.channels = body.get("channels") or {}
        return {"ok": True}


@router.get("/notifications")
def list_notifications(
    limit: int = Query(default=50, le=200), current: CurrentUser = CurrentUserDep
) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(
            select(Notification)
            .where(Notification.tenant_id == current.tenant_id, Notification.channel == "web")
            .order_by(Notification.id.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": n.id, "title": n.title, "body": n.body,
                "read": n.read, "created_at": n.created_at,
            }
            for n in rows
        ]


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        n = session.get(Notification, notification_id)
        if n is None or n.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="通知不存在")
        n.read = True
        return {"ok": True}


class NlSearchIn(BaseModel):
    query: str
    all_regions: bool = False


@router.post("/search/nl")
def nl_search(body: NlSearchIn, current: CurrentUser = CurrentUserDep) -> dict:
    """LLM 解析 DSL → SQL 过滤（关键词/地区）→ Python 侧预算过滤（tech-design.md §5.3）。"""
    filters = parse_query(body.query)
    with session_scope() as session:
        stmt = (
            select(Announcement, Project)
            .join(Project, Project.announcement_id == Announcement.id, isouter=True)
            .order_by(Announcement.publish_time.desc().nullslast())
            .limit(200)
        )
        if keyword := filters.get("keyword"):
            stmt = stmt.where(Announcement.title.ilike(f"%{keyword}%"))
        # 地区口径与推荐/普通查询统一：句子里说了地区就用它，否则默认画像「仅关注地区」
        if nl_region := filters.get("region"):
            active_regions = [nl_region]
        elif not body.all_regions:
            active_regions = get_filter_regions(session, current.tenant_id)
        else:
            active_regions = []
        if (clause := region_filter_clause(active_regions)) is not None:
            stmt = stmt.where(clause)
        rows = session.execute(stmt).all()

        items = []
        for ann, project in rows:
            if project and (main := filters.get("category_main")):
                if (project.category or {}).get("main") != main:
                    continue
            budget = parse_budget_yuan(
                ((project.fields or {}).get("budget") or {}).get("value") if project else None
            )
            if (bmin := filters.get("budget_min")) and (budget is None or budget < bmin):
                continue
            if (bmax := filters.get("budget_max")) and (budget is None or budget > bmax):
                continue
            items.append(
                {
                    "id": ann.id, "title": ann.title, "url": ann.url,
                    "ann_type": ann.ann_type, "region": ann.region, "buyer": ann.buyer,
                    "publish_time": ann.publish_time, "status": ann.status,
                    "summary": project.summary if project else None,
                }
            )
        return {
            "filters": filters,
            "items": items[:50],
            "total": len(items),
            "region_scope": active_regions,
        }
