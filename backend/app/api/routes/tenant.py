"""租户层接口：推荐、跟进、画像、订阅、通知、NL 搜索。全部按 tenant_id 强制隔离。"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, select

from app.ai import websearch
from app.ai.llm_config import friendly_llm_error
from app.ai.nl_search import parse_query
from app.ai.profile_materials import project_confirmed_fact, validate_fact_value
from app.ai.profile_suggest import suggest_profile
from app.core import storage
from app.core.audit import record_audit
from app.core.db import session_scope
from app.core.kv import (
    DEFAULT_QUOTA_NL_SEARCH,
    DEFAULT_QUOTA_PROFILE_SUGGEST,
    KEY_QUOTA_NL_SEARCH,
    KEY_QUOTA_PROFILE_SUGGEST,
    get_setting,
)
from app.core.ratelimit import acquire_cooldown, try_consume_quota
from app.core.security import AdminDep, CurrentUser, CurrentUserDep
from app.matching.engine import parse_budget_yuan
from app.matching.profiles import (
    get_filter_regions,
    get_watched_source_ids,
    region_filter_clause,
    upsert_profile,
)
from app.models import (
    Announcement,
    CompanyProfile,
    MatchResult,
    Notification,
    ProfileEvidence,
    ProfileFact,
    ProfileMaterial,
    Project,
    Subscription,
    Tenant,
)
from app.parsing.documents import parse_attachment

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

FOLLOW_STATUSES = ("待看", "跟进中", "放弃", "已投标")
PROFILE_MATERIAL_MAX_BYTES = 20 * 1024 * 1024
PROFILE_MATERIAL_EXTENSIONS = {".pdf", ".pptx", ".docx", ".txt"}
PROFILE_MATERIAL_DOCUMENT_TYPES = {
    "award_notice",
    "contract",
    "acceptance_report",
    "company_presentation",
    "solution",
    "case_study",
    "product_manual",
    "whitepaper",
    "qualification",
    "other",
}


def infer_profile_document_type(filename: str) -> str:
    """按文件名做保守分类；无法判断时归为其他企业资料，由通用 Prompt 处理。"""
    name = filename.lower()
    rules = (
        (("验收", "竣工"), "acceptance_report"),
        (("中标", "成交", "award"), "award_notice"),
        (("合同", "contract"), "contract"),
        (("资质", "证书", "认证"), "qualification"),
        (("案例", "业绩"), "case_study"),
        (("白皮书", "whitepaper"), "whitepaper"),
        (("手册", "manual", "产品说明"), "product_manual"),
        (("解决方案", "方案"), "solution"),
        (("公司介绍", "企业介绍", "演示", "presentation"), "company_presentation"),
    )
    return next((kind for words, kind in rules if any(word in name for word in words)), "other")


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
                    "score_details": match.score_details,
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
        record_audit(
            session, current, "follow.update",
            target=f"match:{match_id}", detail={"status": body.status},
        )
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
        tenant = session.get(Tenant, current.tenant_id)
        # 企业名称以注册租户名为唯一权威（审批过的账号身份），画像内不可另起名字
        return (
            EMPTY_PROFILE
            | (profile.data if profile else {})
            | {
                "name": tenant.name,
                "updated_at": profile.updated_at.isoformat() if profile else None,
            }
        )


@router.put("/profile")
def put_profile(body: dict, current: CurrentUser = CurrentUserDep) -> dict:
    """保存画像并生效。画像有实质变更时异步触发重评估（近 7 天商机按新画像重跑，
    10 分钟冷却防抖）；rematch 字段告知前端触发结果。"""
    data = {k: body.get(k, v) for k, v in EMPTY_PROFILE.items()}
    with session_scope() as session:
        # 强制覆盖为注册企业名：保证右上角、画像、匹配 Prompt、AI 检索口径一致
        data["name"] = session.get(Tenant, current.tenant_id).name
        profile = session.scalar(
            select(CompanyProfile).where(CompanyProfile.tenant_id == current.tenant_id)
        )
        old = (
            {k: (profile.data or {}).get(k, v) for k, v in EMPTY_PROFILE.items()}
            if profile
            else None
        )
        upsert_profile(session, current.tenant_id, data)
        if old != data:
            changed = sorted(
                k for k in EMPTY_PROFILE if (old or {}).get(k) != data.get(k)
            )
            record_audit(session, current, "profile.save", detail={"changed": changed})
    if old == data:
        return {"ok": True, "rematch": "unchanged"}
    return {"ok": True, "rematch": _queue_profile_rematch(current.tenant_id)}


def _queue_profile_rematch(tenant_id: int) -> str:
    """复用画像保存后的异步重评估策略。"""
    if not acquire_cooldown(f"rematch:{tenant_id}", 600):
        return "cooldown"
    try:
        from app.tasks.pipeline import rematch_tenant_task

        rematch_tenant_task.delay(tenant_id)
        return "queued"
    except Exception:
        logger.exception("重评估任务入队失败 tenant=%s", tenant_id)
        return "queue_failed"


class ProfileSuggestIn(BaseModel):
    name: str


@router.post("/profile/suggest")
def profile_suggest(body: ProfileSuggestIn, current: CurrentUser = CurrentUserDep) -> dict:
    """AI 企业画像草稿：企业名 → 联网搜索 → LLM 整理（不落库，供前端预填后人工确认再保存）。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入企业名称")
    if not websearch.available():
        raise HTTPException(
            status_code=400, detail="未配置联网搜索（METASO_API_KEY），无法自动生成，请手动填写画像"
        )
    with session_scope() as session:
        quota = int(get_setting(session, KEY_QUOTA_PROFILE_SUGGEST, DEFAULT_QUOTA_PROFILE_SUGGEST))
    if not try_consume_quota(current.tenant_id, "profile_suggest", quota):
        raise HTTPException(
            status_code=429, detail="今日 AI 画像生成次数已用完，请明天再试或手动填写"
        )
    try:
        return suggest_profile(name, tenant_id=current.tenant_id)
    except Exception as exc:
        logger.exception("AI 画像生成失败")
        raise HTTPException(
            status_code=502, detail=f"生成画像失败：{friendly_llm_error(exc) or exc}"
        ) from exc


def _material_dict(material: ProfileMaterial, fact_count: int = 0) -> dict:
    return {
        "id": material.id,
        "filename": material.filename,
        "source_type": material.source_type,
        "document_type": material.document_type,
        "content_type": material.content_type,
        "parse_status": material.parse_status,
        "needs_ocr": material.needs_ocr,
        "error": material.error,
        "fact_count": fact_count,
        "created_at": material.created_at,
    }


@router.get("/profile/materials")
def list_profile_materials(current: CurrentUser = CurrentUserDep) -> list[dict]:
    with session_scope() as session:
        materials = session.scalars(
            select(ProfileMaterial)
            .where(ProfileMaterial.tenant_id == current.tenant_id)
            .order_by(ProfileMaterial.id.desc())
        ).all()
        counts = {
            material.id: sum(
                1
                for _ in session.scalars(
                    select(ProfileEvidence).where(ProfileEvidence.material_id == material.id)
                )
            )
            for material in materials
        }
        return [_material_dict(material, counts.get(material.id, 0)) for material in materials]


@router.post("/profile/materials")
async def upload_profile_material(
    file: Annotated[UploadFile, File()],
    document_type: Annotated[str, Form()] = "award_notice",
    current: CurrentUser = CurrentUserDep,
) -> dict:
    """上传企业材料；原件入 MinIO，文本本地解析，案例抽取交给后台任务。"""
    filename = Path(file.filename or "material").name
    suffix = Path(filename).suffix.lower()
    if suffix not in PROFILE_MATERIAL_EXTENSIONS:
        raise HTTPException(status_code=422, detail="仅支持 PDF、PPTX、DOCX、TXT 文件")
    auto_detected = document_type == "auto"
    if auto_detected:
        document_type = infer_profile_document_type(filename)
    if document_type not in PROFILE_MATERIAL_DOCUMENT_TYPES:
        raise HTTPException(status_code=422, detail="不支持的企业资料类型")
    data = await file.read(PROFILE_MATERIAL_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="文件内容为空")
    if len(data) > PROFILE_MATERIAL_MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过 20MB")
    try:
        parsed_text, needs_ocr = parse_attachment(filename, data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"文件解析失败：{exc}") from exc

    object_key = f"profiles/{current.tenant_id}/{uuid4().hex}-{filename}"
    stored_key = storage.put_bytes(
        object_key, data, file.content_type or "application/octet-stream"
    )
    if stored_key is None:
        raise HTTPException(status_code=503, detail="文件存储暂不可用，请稍后重试")
    with session_scope() as session:
        material = ProfileMaterial(
            tenant_id=current.tenant_id,
            source_type="auto_detected_document" if auto_detected else "uploaded_document",
            document_type=document_type,
            filename=filename,
            content_type=file.content_type,
            object_key=stored_key,
            parsed_text=parsed_text or None,
            parse_status="needs_ocr" if needs_ocr else ("parsed" if parsed_text else "no_text"),
            needs_ocr=needs_ocr,
            error=(
                "扫描件暂不支持 OCR，请上传可复制文字的 PDF"
                if needs_ocr
                else ("未从文件中读取到文字；图片中的文字暂不支持识别" if not parsed_text else None)
            ),
        )
        session.add(material)
        session.flush()
        material_id = material.id
        record_audit(
            session, current, "material.upload",
            target=f"material:{material_id} {filename}",
        )
    if parsed_text and not needs_ocr:
        try:
            from app.tasks.pipeline import profile_material_extract_task

            profile_material_extract_task.delay(material_id)
        except Exception as exc:  # 材料已安全入库，队列失败允许前端重试
            logger.exception("画像材料抽取任务入队失败 material=%s", material_id)
            with session_scope() as session:
                material = session.get(ProfileMaterial, material_id)
                material.error = f"抽取任务提交失败：{exc}"[:1000]
    with session_scope() as session:
        return _material_dict(session.get(ProfileMaterial, material_id))


@router.post("/profile/materials/{material_id}/extract")
def retry_profile_material_extract(
    material_id: int, current: CurrentUser = CurrentUserDep
) -> dict:
    with session_scope() as session:
        material = session.get(ProfileMaterial, material_id)
        if material is None or material.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="材料不存在")
        if material.parse_status == "extracting":
            raise HTTPException(status_code=409, detail="材料正在抽取中，请勿重复提交")
        if not material.parsed_text or material.needs_ocr:
            raise HTTPException(status_code=422, detail="材料没有可提取文本")
        material.parse_status = "parsed"
        material.error = None
    try:
        from app.tasks.pipeline import profile_material_extract_task

        profile_material_extract_task.delay(material_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="抽取任务提交失败，请稍后重试") from exc
    return {"ok": True}


@router.delete("/profile/materials/{material_id}")
def delete_profile_material(material_id: int, current: CurrentUser = CurrentUserDep) -> dict:
    object_key: str | None = None
    with session_scope() as session:
        material = session.get(ProfileMaterial, material_id)
        if material is None or material.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="材料不存在")
        object_key = material.object_key
        fact_ids = session.scalars(
            select(ProfileEvidence.fact_id).where(ProfileEvidence.material_id == material.id)
        ).all()
        session.execute(delete(ProfileEvidence).where(ProfileEvidence.material_id == material.id))
        session.flush()
        if fact_ids:
            for fact in session.scalars(
                select(ProfileFact).where(ProfileFact.id.in_(fact_ids))
            ):
                has_other_evidence = session.scalar(
                    select(ProfileEvidence.id).where(ProfileEvidence.fact_id == fact.id).limit(1)
                )
                if fact.status == "confirmed":
                    if not has_other_evidence:
                        fact.source_strength = "tenant_confirmed"
                elif not has_other_evidence:
                    session.delete(fact)
        record_audit(
            session, current, "material.delete",
            target=f"material:{material_id} {material.filename}",
        )
        session.delete(material)
    if object_key:
        storage.delete_object(object_key)
    return {"ok": True}


@router.get("/profile/facts")
def list_profile_facts(
    status: str = Query(default="pending"), current: CurrentUser = CurrentUserDep
) -> list[dict]:
    if status not in {"pending", "confirmed", "rejected"}:
        raise HTTPException(status_code=422, detail="无效的事实状态")
    with session_scope() as session:
        facts = session.scalars(
            select(ProfileFact)
            .where(ProfileFact.tenant_id == current.tenant_id, ProfileFact.status == status)
            .order_by(ProfileFact.id.desc())
        ).all()
        evidence_by_fact = {}
        if facts:
            evidence_rows = session.execute(
                select(ProfileEvidence, ProfileMaterial)
                .join(ProfileMaterial, ProfileMaterial.id == ProfileEvidence.material_id)
                .where(
                    ProfileEvidence.tenant_id == current.tenant_id,
                    ProfileEvidence.fact_id.in_([fact.id for fact in facts]),
                )
                .order_by(ProfileEvidence.fact_id, ProfileEvidence.id)
            ).all()
            for evidence, material in evidence_rows:
                evidence_by_fact.setdefault(evidence.fact_id, (evidence, material))
        out = []
        for fact in facts:
            ev, material = evidence_by_fact.get(fact.id, (None, None))
            out.append(
                {
                    "id": fact.id,
                    "fact_type": fact.fact_type,
                    "value": fact.value,
                    "confidence": fact.confidence,
                    "source_strength": fact.source_strength,
                    "status": fact.status,
                    "evidence": {
                        "material_id": material.id,
                        "filename": material.filename,
                        "page": ev.page,
                        "quote": ev.quote,
                    } if ev and material else None,
                    "created_at": fact.created_at,
                }
            )
        return out


class ProfileFactConfirmIn(BaseModel):
    value: dict | None = None


@router.post("/profile/facts/{fact_id}/confirm")
def confirm_profile_fact(
    fact_id: int, body: ProfileFactConfirmIn, current: CurrentUser = CurrentUserDep
) -> dict:
    with session_scope() as session:
        fact = session.get(ProfileFact, fact_id)
        if fact is None or fact.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="候选事实不存在")
        if fact.status != "pending":
            raise HTTPException(status_code=409, detail="该事实已经处理")
        try:
            value = validate_fact_value(fact.fact_type, body.value or fact.value)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="候选事实字段不完整或格式错误") from exc
        if fact.fact_type == "project_case" and value["company_role"] not in {
            "winner",
            "supplier",
            "consortium_member",
        }:
            raise HTTPException(
                status_code=422,
                detail="只有中标人、成交供应商或联合体成员可以确认为正式案例，请先修正企业角色",
            )
        fact.value = value
        fact.status = "confirmed"
        fact.confirmed_by = current.user_id
        fact.confirmed_at = datetime.now(UTC)
        projected = project_confirmed_fact(session, fact, value)
        record_audit(session, current, "fact.confirm", target=f"fact:{fact_id}")
    return {
        "ok": True,
        "projected": projected,
        "rematch": _queue_profile_rematch(current.tenant_id) if projected else False,
    }


@router.post("/profile/facts/{fact_id}/reject")
def reject_profile_fact(fact_id: int, current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        fact = session.get(ProfileFact, fact_id)
        if fact is None or fact.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="候选事实不存在")
        if fact.status != "pending":
            raise HTTPException(status_code=409, detail="该事实已经处理")
        fact.status = "rejected"
        fact.confirmed_by = current.user_id
        fact.confirmed_at = datetime.now(UTC)
        record_audit(session, current, "fact.reject", target=f"fact:{fact_id}")
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
                "channels": DEFAULT_CHANNELS, "source_ids": [],
            }
        return {
            "min_star": sub.min_star,
            "immediate": sub.immediate,
            "daily_digest": sub.daily_digest,
            "channels": DEFAULT_CHANNELS | (sub.channels or {}),
            "source_ids": sub.source_ids or [],
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
        # 关注的数据源：只收合法 int id；空列表 = 不限
        sub.source_ids = [int(i) for i in (body.get("source_ids") or []) if str(i).isdigit()]
        # channels 含 webhook/邮箱地址，审计只记开启了哪些渠道
        record_audit(
            session, current, "subscription.save",
            detail={
                "min_star": sub.min_star,
                "immediate": sub.immediate,
                "daily_digest": sub.daily_digest,
                "channels_enabled": sorted(
                    k for k, v in (sub.channels or {}).items() if v.get("enabled")
                ),
                "source_ids": sub.source_ids,
            },
        )
        return {"ok": True}


@router.get("/tenant/audit-logs")
def tenant_audit_logs(
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current: CurrentUser = AdminDep,
) -> dict:
    """本租户操作日志（tenant_admin 可查本企业成员的操作，强制 tenant_id 隔离）。"""
    from app.core.audit import audit_log_dict
    from app.models import AuditLog

    limit = max(1, min(limit, 200))
    with session_scope() as session:
        stmt = select(AuditLog).where(AuditLog.tenant_id == current.tenant_id)
        if action:
            stmt = stmt.where(AuditLog.action.like(f"{action}%"))
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(
            stmt.order_by(AuditLog.id.desc()).limit(limit).offset(max(0, offset))
        ).all()
        return {"items": [audit_log_dict(r) for r in rows], "total": total or 0}


@router.get("/notifications")
def list_notifications(
    limit: int = Query(default=50, le=200), current: CurrentUser = CurrentUserDep
) -> list[dict]:
    with session_scope() as session:
        notifications = session.scalars(
            select(Notification)
            .where(Notification.tenant_id == current.tenant_id, Notification.channel == "web")
            .order_by(Notification.id.desc())
            .limit(limit)
        ).all()

        # 旧版日报没有保存关联 ID；按当时生成日报的同一时间窗口和排序规则恢复。
        legacy_digest_match_ids: dict[int, list[int]] = {}
        for notification in notifications:
            if (
                notification.related_match_id is None
                and not notification.related_match_ids
                and notification.title.startswith("商机日报：")
            ):
                legacy_digest_match_ids[notification.id] = list(session.scalars(
                    select(MatchResult.id)
                    .where(
                        MatchResult.tenant_id == current.tenant_id,
                        MatchResult.created_at >= notification.created_at - timedelta(days=1),
                        MatchResult.created_at <= notification.created_at,
                        MatchResult.star >= 3,
                    )
                    .order_by(MatchResult.star.desc(), MatchResult.match_score.desc())
                    .limit(20)
                ).all())
        match_ids = {
            match_id
            for notification in notifications
            for match_id in (
                [notification.related_match_id]
                + (notification.related_match_ids or [])
                + legacy_digest_match_ids.get(notification.id, [])
            )
            if match_id is not None
        }
        opportunity_by_match_id = {}
        if match_ids:
            opportunities = session.execute(
                select(MatchResult.id, Project.announcement_id, Announcement.title)
                .join(Project, Project.id == MatchResult.project_id)
                .join(Announcement, Announcement.id == Project.announcement_id)
                .where(
                    MatchResult.tenant_id == current.tenant_id,
                    MatchResult.id.in_(match_ids),
                )
            ).all()
            opportunity_by_match_id = {
                match_id: {"announcement_id": announcement_id, "title": title}
                for match_id, announcement_id, title in opportunities
            }

        def related_opportunities(notification: Notification) -> list[dict]:
            ids = notification.related_match_ids or legacy_digest_match_ids.get(notification.id, [])
            if not ids and notification.related_match_id is not None:
                ids = [notification.related_match_id]
            return [opportunity_by_match_id[mid] for mid in ids if mid in opportunity_by_match_id]

        result = []
        for notification in notifications:
            linked = related_opportunities(notification)
            result.append({
                "id": notification.id,
                "title": notification.title,
                "body": notification.body,
                "read": notification.read,
                "created_at": notification.created_at,
                "announcement_id": linked[0]["announcement_id"] if linked else None,
                "opportunities": linked,
            })
        return result


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        n = session.get(Notification, notification_id)
        if n is None or n.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="通知不存在")
        n.read = True
        return {"ok": True}


@router.delete("/notifications/{notification_id}")
def delete_notification(notification_id: int, current: CurrentUser = CurrentUserDep) -> dict:
    """删除当前租户的一条站内通知；关联商机和匹配结果不受影响。"""
    with session_scope() as session:
        notification = session.get(Notification, notification_id)
        if notification is None or notification.tenant_id != current.tenant_id:
            raise HTTPException(status_code=404, detail="通知不存在")
        session.delete(notification)
        return {"ok": True}


class NlSearchIn(BaseModel):
    query: str
    all_regions: bool = False
    include_results: bool = False


@router.post("/search/nl")
def nl_search(body: NlSearchIn, current: CurrentUser = CurrentUserDep) -> dict:
    """LLM 解析 DSL → SQL 过滤（关键词/地区）→ Python 侧预算过滤（tech-design.md §5.3）。"""
    with session_scope() as session:
        quota = int(get_setting(session, KEY_QUOTA_NL_SEARCH, DEFAULT_QUOTA_NL_SEARCH))
    # 超出当日配额：跳过 LLM 解析，整句降级为关键词搜索（与解析失败同一兜底路径）
    degraded = not try_consume_quota(current.tenant_id, "nl_search", quota)
    filters = {"keyword": body.query} if degraded else parse_query(body.query, current.tenant_id)
    with session_scope() as session:
        stmt = (
            select(Announcement, Project)
            .join(Project, Project.announcement_id == Announcement.id, isouter=True)
            .order_by(Announcement.publish_time.desc().nullslast())
            .limit(200)
        )
        # 与普通查询同口径：默认隐藏结果类公告
        if not body.include_results:
            stmt = stmt.where(Announcement.biddable.isnot(False))
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
        # 租户「关注的数据源」：与普通查询/推荐口径一致
        if watched := get_watched_source_ids(session, current.tenant_id):
            stmt = stmt.where(Announcement.source_id.in_(watched))
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
            "degraded": "quota" if degraded else None,
        }
