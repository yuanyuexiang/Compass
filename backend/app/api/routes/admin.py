"""平台管理员接口：租户审批/启停、LLM 用量报表。仅 platform_admin 可用。"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.core.db import session_scope
from app.core.security import CurrentUser, PlatformAdminDep, clear_block_cache
from app.models import CompanyProfile, LlmUsage, Tenant, User

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
                "tenant_name": names.get(tid, "（公共层）") if tid is not None else "（公共层）",
                "scene": scene,
                "calls": calls,
                "total_tokens": int(tokens),
            }
            for tid, scene, calls, tokens in rows
        ],
    }
