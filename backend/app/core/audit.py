"""结构化日志写入：操作日志（谁做了什么）与运行日志（流水线事件）。

显式埋点，与业务同事务（业务回滚则日志一并回滚，不会出现"记了没做"）。
detail 严禁写入密码、API Key、JWT 等敏感信息——只记变更摘要。
"""

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.security import CurrentUser
from app.models import AuditLog, SystemEvent, User

logger = logging.getLogger(__name__)


def record_audit(
    session: Session,
    current: CurrentUser | None,
    action: str,
    *,
    target: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    username: str | None = None,
) -> None:
    """写一条操作日志。current 为 None 时（如登录失败）用 username 参数记操作者。"""
    user_id = tenant_id = None
    if current is not None:
        user_id, tenant_id = current.user_id, current.tenant_id
        if username is None:
            user = session.get(User, current.user_id)
            username = user.username if user is not None else None
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            username=username,
            action=action,
            target=target[:255] if target else None,
            detail=detail,
            ip=ip,
        )
    )


def record_event(
    session: Session,
    event: str,
    message: str,
    *,
    level: str = "info",
    detail: dict | None = None,
) -> None:
    """写一条系统运行事件（流水线关键节点；高频事件调用方自行用 cooldown 防刷屏）。"""
    session.add(SystemEvent(level=level, event=event, message=message, detail=detail))


def audit_log_dict(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "username": row.username,
        "action": row.action,
        "target": row.target,
        "detail": row.detail,
        "ip": row.ip,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def system_event_dict(row: SystemEvent) -> dict:
    return {
        "id": row.id,
        "level": row.level,
        "event": row.event,
        "message": row.message,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def client_ip(request: Request) -> str | None:
    """客户端 IP：生产经 Traefik 反代取 X-Forwarded-For 首址，本地直连退回对端地址。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None
