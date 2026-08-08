"""平台管理员接口：租户审批/启停、LLM 用量报表。仅 platform_admin 可用。"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.audit import record_audit
from app.core.db import session_scope
from app.core.kv import (
    DEFAULT_CRAWL_INTERVAL_MINUTES,
    KEY_CRAWL_INTERVAL,
    KEY_LAST_AUTO_CRAWL,
    get_setting,
)
from app.core.ratelimit import counter_get, note_get
from app.core.security import CurrentUser, PlatformAdminDep, clear_block_cache
from app.models import (
    Announcement,
    CompanyProfile,
    LlmUsage,
    MatchResult,
    Source,
    SourceStatus,
    Subscription,
    Tenant,
    User,
)

router = APIRouter(prefix="/api/admin")
logger = logging.getLogger(__name__)

TENANT_STATUS_LABELS = {"pending": "待审批", "active": "已开通", "disabled": "已停用"}


@router.get("/tenants")
def list_tenants(current: CurrentUser = PlatformAdminDep) -> dict:
    with session_scope() as session:
        # 平台租户是 admin 挂靠处，不参与业务，不出现在租户管理列表
        tenants = session.scalars(
            select(Tenant).where(Tenant.is_platform.is_(False)).order_by(Tenant.created_at.desc())
        ).all()
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
                "admin_phone": admins[t.id].phone if t.id in admins else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "is_self": t.id == current.tenant_id,
            }
            for t in tenants
        ]
        return {"items": items, "total": len(items)}


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    """平台运营视角的租户详情；通知配置仅返回开关，不泄露地址或 webhook。"""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None or tenant.is_platform:
            raise HTTPException(status_code=404, detail="租户不存在")
        profile = session.scalar(
            select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id)
        )
        subscription = session.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        )
        profile_data = profile.data if profile else {}
        fillable = (
            "description", "products", "services", "industries", "regions",
            "certifications", "brands", "cases_text",
        )
        filled = sum(bool(profile_data.get(key)) for key in fillable)
        profile_filter = profile_data.get("filter") or {}
        filled += bool(profile_filter.get("regions") or profile_filter.get("min_budget"))
        channels = subscription.channels if subscription else {}
        enabled_channels = sorted(
            key for key, value in (channels or {}).items()
            if isinstance(value, dict) and value.get("enabled")
        )
        match_rows = dict(
            session.execute(
                select(MatchResult.follow_status, func.count(MatchResult.id))
                .where(MatchResult.tenant_id == tenant_id, MatchResult.created_at >= cutoff)
                .group_by(MatchResult.follow_status)
            ).all()
        )
        member_count = session.scalar(
            select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
        ) or 0
        recommendation_count = sum(match_rows.values())
        return {
            "id": tenant.id,
            "profile": profile_data,
            "profile_updated_at": profile.updated_at.isoformat() if profile else None,
            "profile_completeness": round(filled * 100 / 9),
            "subscription": {
                "min_star": subscription.min_star if subscription else 4,
                "immediate": subscription.immediate if subscription else True,
                "daily_digest": subscription.daily_digest if subscription else True,
                "source_count": len(subscription.source_ids or []) if subscription else 0,
                "source_scope_all": not bool(subscription and subscription.source_ids),
                "enabled_channels": enabled_channels,
            },
            "activity_30d": {
                "members": member_count,
                "recommendations": recommendation_count,
                "following": match_rows.get("跟进中", 0),
                "bid": match_rows.get("已投标", 0),
            },
        }


def _reject_platform_tenant(tenant: Tenant, action: str) -> None:
    """平台租户是 admin 挂靠处，停用/删除会把平台管理员锁在门外，一律拒绝。"""
    if tenant.is_platform:
        raise HTTPException(status_code=422, detail=f"平台租户不可{action}")


def _set_tenant_state(
    tenant_id: int, current: CurrentUser, *, status: str, enabled: bool, action: str = "tenant.set"
) -> dict:
    if tenant_id == current.tenant_id and not enabled:
        raise HTTPException(status_code=422, detail="不能停用自己所在的租户")
    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="租户不存在")
        if not enabled:
            _reject_platform_tenant(tenant, "停用")
        tenant.status = status
        tenant.enabled = enabled
        record_audit(session, current, action, target=f"tenant:{tenant.id} {tenant.name}")
    clear_block_cache()
    return {"id": tenant_id, "status": status, "enabled": enabled}


@router.post("/tenants/{tenant_id}/approve")
def approve_tenant(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    return _set_tenant_state(
        tenant_id, current, status="active", enabled=True, action="tenant.approve"
    )


@router.post("/tenants/{tenant_id}/enable")
def enable_tenant(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    return _set_tenant_state(
        tenant_id, current, status="active", enabled=True, action="tenant.enable"
    )


@router.post("/tenants/{tenant_id}/disable")
def disable_tenant(tenant_id: int, current: CurrentUser = PlatformAdminDep) -> dict:
    return _set_tenant_state(
        tenant_id, current, status="disabled", enabled=False, action="tenant.disable"
    )


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
        _reject_platform_tenant(tenant, "删除")
        if tenant.status == "active":
            raise HTTPException(status_code=422, detail="正常运营的租户请先停用，再执行删除")
        name = tenant.name
        record_audit(session, current, "tenant.delete", target=f"tenant:{tenant_id} {name}")
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
    from app.tasks.pipeline import auto_pipeline_backpressure, auto_window_minutes_between

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
        pause_reason = auto_pipeline_backpressure(session, now)

    # 调度活性按窗口内时间算：夜间关窗不采集是设计行为，裸时间差会每天凌晨误报停摆；
    # 背压暂停同理——采集是主动停的，不算 beat 故障（暂停原因单独透出）。
    beat_ok = True
    if last_auto and not pause_reason:
        gap = auto_window_minutes_between(datetime.fromisoformat(last_auto), now)
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
            "fallback_last": note_get("llm_fallback_last"),
            "last_success_at": llm_last_success.isoformat() if llm_last_success else None,
        },
        "scheduler": {
            "ok": beat_ok,
            "last_auto_crawl_at": last_auto,
            "interval_minutes": interval,
            "paused_reason": pause_reason,
        },
        "stale_sources": stale_sources,
    }


LLM_SCENES = {
    "default": "默认模型",
    "extract": "字段提取",
    "match": "匹配精排",
    "match_eval": "离线匹配评测",
    "nl_search": "NL 搜索",
    "profile_suggest": "AI 画像",
    "profile_material": "企业材料抽取",
    "source_suggest": "AI 识别数据源",
}


class LlmProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    api_key: str = ""  # 空 = 保留已存密钥（接口永不回传明文，前端只提交改动）
    base_url: str = Field(default="", max_length=200)


class LlmSceneModelIn(BaseModel):
    provider: str
    # 空模型表示前端仍在选择中；保存时会被过滤，不应让整份配置返回 422。
    model: str = Field(default="", max_length=100)


class LlmConfigIn(BaseModel):
    providers: list[LlmProviderIn] = []
    scene_models: dict[str, LlmSceneModelIn | None] = {}
    fallback: LlmSceneModelIn | None = None


@router.get("/llm")
def get_llm_config(current: CurrentUser = PlatformAdminDep) -> dict:
    from app.core.crypto import decrypt, mask
    from app.core.kv import KEY_LLM_FALLBACK, KEY_LLM_PROVIDERS, KEY_LLM_SCENE_MODELS, get_setting

    cutoff = datetime.now(UTC) - timedelta(days=7)
    with session_scope() as session:
        providers = get_setting(session, KEY_LLM_PROVIDERS, []) or []
        scene_models = get_setting(session, KEY_LLM_SCENE_MODELS, {}) or {}
        fallback = get_setting(session, KEY_LLM_FALLBACK, None)
        usage = session.execute(
            select(
                LlmUsage.model,
                func.count(LlmUsage.id),
                func.coalesce(func.sum(LlmUsage.total_tokens), 0),
            )
            .where(LlmUsage.created_at >= cutoff)
            .group_by(LlmUsage.model)
        ).all()
    return {
        "providers": [
            {
                "name": p.get("name"),
                "base_url": p.get("base_url") or "",
                "api_key_masked": mask(decrypt(p.get("api_key") or "")),
            }
            for p in providers
        ],
        "scene_models": scene_models,
        "fallback": fallback,
        "scenes": LLM_SCENES,
        "usage_7d": [
            {"model": m or "（未知）", "calls": c, "total_tokens": int(t)} for m, c, t in usage
        ],
    }


@router.put("/llm")
def put_llm_config(body: LlmConfigIn, current: CurrentUser = PlatformAdminDep) -> dict:
    from app.ai.llm_config import invalidate_llm_config_cache
    from app.core.crypto import encrypt
    from app.core.kv import (
        KEY_LLM_FALLBACK,
        KEY_LLM_PROVIDERS,
        KEY_LLM_SCENE_MODELS,
        get_setting,
        set_setting,
    )

    with session_scope() as session:
        old = {p.get("name"): p for p in get_setting(session, KEY_LLM_PROVIDERS, []) or []}
        stored, names = [], set()
        for p in body.providers:
            name = p.name.strip()
            if not name or name in names:
                continue
            if p.api_key.strip():
                enc = encrypt(p.api_key.strip())
            elif name in old:
                enc = old[name].get("api_key") or ""
            else:
                raise HTTPException(status_code=422, detail=f"供应商「{name}」缺少 API Key")
            names.add(name)
            stored.append({"name": name, "api_key": enc, "base_url": p.base_url.strip()})
        scene_models = {
            k: {"provider": v.provider, "model": v.model.strip()}
            for k, v in body.scene_models.items()
            if k in LLM_SCENES and v is not None and v.provider in names and v.model.strip()
        }
        fallback = (
            {"provider": body.fallback.provider, "model": body.fallback.model.strip()}
            if body.fallback and body.fallback.provider in names and body.fallback.model.strip()
            else None
        )
        set_setting(session, KEY_LLM_PROVIDERS, stored)
        set_setting(session, KEY_LLM_SCENE_MODELS, scene_models)
        set_setting(session, KEY_LLM_FALLBACK, fallback)
        # 审计只记供应商名与场景映射，密钥（含密文）绝不落日志
        record_audit(
            session, current, "llm.config_save",
            detail={"providers": sorted(names), "scene_models": scene_models},
        )
    invalidate_llm_config_cache()
    return {"ok": True, "providers": len(stored)}


@router.post("/llm/test")
def test_llm_provider(body: LlmSceneModelIn, current: CurrentUser = PlatformAdminDep) -> dict:
    """用已存密钥对指定 供应商+模型 发一次最小调用，实测连通性/余额/密钥有效性。"""
    from app.ai.llm_config import extract_completion, friendly_llm_error, provider_base_url
    from app.core.crypto import decrypt
    from app.core.kv import KEY_LLM_PROVIDERS, get_setting

    try:
        with session_scope() as session:
            providers = {
                p.get("name"): p for p in get_setting(session, KEY_LLM_PROVIDERS, []) or []
            }
        p = providers.get(body.provider)
        key = decrypt(p.get("api_key") or "") if p else ""
        if not key:
            return {"ok": False, "message": "该供应商尚未保存有效的 API Key，请重新编辑并保存"}
        target = {
            "model": body.model,
            "api_key": key,
            "base_url": provider_base_url(body.provider, p.get("base_url")),
        }
        extract_completion(
            # 注意：json_object 模式要求提示词里出现 "json" 字样（DeepSeek/OpenAI 通用约束）
            [{"role": "user", "content": '输出 json：{"ok": true}'}],
            scene="admin_test",
            model_override=target,
            max_tokens=20,
            timeout=25,
        )
        return {"ok": True, "message": "连接正常，密钥有效"}
    except Exception as exc:  # noqa: BLE001  测试端点绝不能因供应商/配置异常返回 500
        logger.exception(
            "LLM 连接测试失败（provider=%s, model=%s）", body.provider, body.model
        )
        message = friendly_llm_error(exc)
        if message is None:
            message = "连接测试失败，请检查 Base URL、模型名和服务端日志"
        return {"ok": False, "message": message}


@router.get("/audit-logs")
def list_audit_logs(
    tenant_id: int | None = None,
    action: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current: CurrentUser = PlatformAdminDep,
) -> dict:
    """操作日志（全平台）：按租户/动作前缀/关键词（操作者或对象）过滤，倒序分页。"""
    from sqlalchemy import or_

    from app.core.audit import audit_log_dict
    from app.models import AuditLog

    limit = max(1, min(limit, 200))
    with session_scope() as session:
        stmt = select(AuditLog)
        if tenant_id is not None:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditLog.action.like(f"{action}%"))
        if q:
            stmt = stmt.where(
                or_(AuditLog.username.ilike(f"%{q}%"), AuditLog.target.ilike(f"%{q}%"))
            )
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(
            stmt.order_by(AuditLog.id.desc()).limit(limit).offset(max(0, offset))
        ).all()
        return {"items": [audit_log_dict(r) for r in rows], "total": total or 0}


@router.get("/system-events")
def list_system_events(
    level: str | None = None,
    event: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current: CurrentUser = PlatformAdminDep,
) -> dict:
    """运行日志：流水线关键事件（采集轮次/背压/放弃积压/LLM 故障/健康告警），倒序分页。"""
    from app.core.audit import system_event_dict
    from app.models import SystemEvent

    limit = max(1, min(limit, 200))
    with session_scope() as session:
        stmt = select(SystemEvent)
        if level:
            stmt = stmt.where(SystemEvent.level == level)
        if event:
            stmt = stmt.where(SystemEvent.event.like(f"{event}%"))
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(
            stmt.order_by(SystemEvent.id.desc()).limit(limit).offset(max(0, offset))
        ).all()
        return {"items": [system_event_dict(r) for r in rows], "total": total or 0}


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
