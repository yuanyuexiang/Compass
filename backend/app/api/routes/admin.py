"""平台管理员接口：租户审批/启停、LLM 用量报表。仅 platform_admin 可用。"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.core.db import session_scope
from app.core.kv import (
    DEFAULT_CRAWL_INTERVAL_MINUTES,
    KEY_CRAWL_INTERVAL,
    KEY_LAST_AUTO_CRAWL,
    get_setting,
)
from app.core.ratelimit import counter_get, note_get
from app.core.security import CurrentUser, PlatformAdminDep, clear_block_cache
from app.models import Announcement, CompanyProfile, LlmUsage, Source, SourceStatus, Tenant, User

router = APIRouter(prefix="/api/admin")

TENANT_STATUS_LABELS = {"pending": "待审批", "active": "已开通", "disabled": "已停用"}


@router.get("/tenants")
def list_tenants(current: CurrentUser = PlatformAdminDep) -> dict:
    with session_scope() as session:
        tenants = session.scalars(select(Tenant).order_by(Tenant.created_at.desc())).all()
        user_counts = dict(
            session.execute(
                select(User.tenant_id, func.count(User.id)).group_by(User.tenant_id)
            ).all()
        )
        profiled = set(session.scalars(select(CompanyProfile.tenant_id)).all())
        admins = {
            u.tenant_id: u
            for u in session.scalars(
                select(User).where(User.role.in_(("tenant_admin", "platform_admin")))
            ).all()
        }
        items = [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "status_label": TENANT_STATUS_LABELS.get(t.status, t.status),
                "enabled": t.enabled,
                "user_count": user_counts.get(t.id, 0),
                "has_profile": t.id in profiled,
                "admin_username": admins[t.id].username if t.id in admins else None,
                "admin_email": admins[t.id].email if t.id in admins else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "is_self": t.id == current.tenant_id,
            }
            for t in tenants
        ]
        return {"items": items, "total": len(items)}


def _set_tenant_state(tenant_id: int, current: CurrentUser, *, status: str, enabled: bool) -> dict:
    if tenant_id == current.tenant_id and not enabled:
        raise HTTPException(status_code=422, detail="不能停用自己所在的租户")
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="租户不存在")
        tenant.status = status
        tenant.enabled = enabled
    clear_block_cache()
    return {"id": tenant_id, "status": status, "enabled": enabled}


@router.post("/tenants/{tenant_id}/approve")
def approve_tenant(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    return _set_tenant_state(tenant_id, current, status="active", enabled=True)


@router.post("/tenants/{tenant_id}/enable")
def enable_tenant(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    return _set_tenant_state(tenant_id, current, status="active", enabled=True)


@router.post("/tenants/{tenant_id}/disable")
def disable_tenant(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    return _set_tenant_state(tenant_id, current, status="disabled", enabled=False)


@router.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    """物理删除租户（仅待审批/已停用可删；正常运营的须先停用——防误删的双闸门）。

    级联清理租户层数据；llm_usage 保留作计费底账（报表显示「已删除租户」）；
    该租户申请的待审/驳回源一并删除，已生效的源保留（全局共享资产）、仅解除归属。"""
    from sqlalchemy import delete as sa_delete

    from app.models import (
        MatchResult,
        Notification,
        ProfileChunk,
        Source,
        SourceStatus,
        Subscription,
    )

    if tenant_id == current.tenant_id:
        raise HTTPException(status_code=422, detail="不能删除自己所在的租户")
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="租户不存在")
        if tenant.status == "active":
            raise HTTPException(status_code=422, detail="正常运营的租户请先停用，再执行删除")
        name = tenant.name
        for model in (Notification, MatchResult, ProfileChunk, Subscription, CompanyProfile, User):
            session.execute(sa_delete(model).where(model.tenant_id == tenant_id))
        session.execute(
            sa_delete(Source).where(
                Source.created_by_tenant_id == tenant_id,
                Source.status != SourceStatus.ACTIVE.value,
            )
        )
        session.execute(
            Source.__table__.update()
            .where(Source.created_by_tenant_id == tenant_id)
            .values(created_by_tenant_id=None)
        )
        session.delete(tenant)
    clear_block_cache()
    return {"ok": True, "deleted": name}


PENDING_STATUSES = ("crawled", "cleaned", "attachments_parsed", "ai_extracted", "embedded")


@router.get("/health")
def system_health(current: CurrentUser = PlatformAdminDep) -> dict:
    """系统健康总览：流水线积压、24h 吞吐、LLM 状态、采集源与调度活性。

    历史教训：DeepSeek 欠费是客户先发现的——平台方必须先于用户看到异常。"""
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)
    with session_scope() as session:
        by_status = dict(
            session.execute(
                select(Announcement.status, func.count()).group_by(Announcement.status)
            ).all()
        )
        backlog = {s: by_status.get(s, 0) for s in PENDING_STATUSES if by_status.get(s)}
        crawled_24h = session.scalar(
            select(func.count()).select_from(Announcement).where(Announcement.created_at >= day_ago)
        )
        published_24h = session.scalar(
            select(func.count()).select_from(Announcement).where(
                Announcement.status == "published", Announcement.updated_at >= day_ago
            )
        )
        failed_24h = session.scalar(
            select(func.count()).select_from(Announcement).where(
                Announcement.status == "failed", Announcement.updated_at >= day_ago
            )
        )
        llm_last_success = session.scalar(select(func.max(LlmUsage.created_at)))

        # 采集源活性：active+enabled 且开采超过 48h 但 48h 内无新公告 → 视为可疑停滞
        two_days_ago = now - timedelta(hours=48)
        recent_by_source = dict(
            session.execute(
                select(Announcement.source_id, func.count())
                .where(Announcement.created_at >= two_days_ago)
                .group_by(Announcement.source_id)
            ).all()
        )
        stale_sources = [
            {"id": s.id, "name": s.display_name or s.name,
             "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
            for s in session.scalars(
                select(Source).where(
                    Source.enabled, Source.status == SourceStatus.ACTIVE.value
                )
            ).all()
            if not recent_by_source.get(s.id)
            and (s.created_at is None or s.created_at < two_days_ago)
        ]

        interval = int(get_setting(session, KEY_CRAWL_INTERVAL, DEFAULT_CRAWL_INTERVAL_MINUTES))
        last_auto = get_setting(session, KEY_LAST_AUTO_CRAWL)

    beat_ok = True
    if last_auto:
        gap = (now - datetime.fromisoformat(last_auto)).total_seconds() / 60
        beat_ok = gap < max(interval * 3, 10)

    llm_failures = counter_get("llm_failures")
    return {
        "backlog": backlog,
        "failed_total": by_status.get("failed", 0),
        "last_24h": {
            "crawled": crawled_24h, "published": published_24h, "failed": failed_24h,
        },
        "llm": {
            "consecutive_failures": llm_failures,
            "ok": llm_failures < 3,
            "last_error": note_get("llm_last_error"),
            "last_success_at": llm_last_success.isoformat() if llm_last_success else None,
        },
        "scheduler": {
            "ok": beat_ok,
            "last_auto_crawl_at": last_auto,
            "interval_minutes": interval,
        },
        "stale_sources": stale_sources,
    }


@router.get("/usage")
def usage_report(days: int = 30, current: CurrentUser = PlatformAdminDep) -> dict:
    """近 N 天 LLM 用量：按租户 × 场景聚合（tenant_id 为空 = 公共层提取）。"""
    cutoff = datetime.now(UTC) - timedelta(days=max(1, min(days, 365)))
    with session_scope() as session:
        rows = session.execute(
            select(
                LlmUsage.tenant_id,
                LlmUsage.scene,
                func.count(LlmUsage.id),
                func.coalesce(func.sum(LlmUsage.total_tokens), 0),
            )
            .where(LlmUsage.created_at >= cutoff)
            .group_by(LlmUsage.tenant_id, LlmUsage.scene)
        ).all()
        names = dict(session.execute(select(Tenant.id, Tenant.name)).all())
    return {
        "days": days,
        "items": [
            {
                "tenant_id": tid,
                "tenant_name": (
                    "（公共层）" if tid is None else names.get(tid, f"（已删除租户 #{tid}）")
                ),
                "scene": scene,
                "calls": calls,
                "total_tokens": int(tokens),
            }
            for tid, scene, calls, tokens in rows
        ],
    }
