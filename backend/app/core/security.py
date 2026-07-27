"""认证与租户上下文（tech-design.md §10.3）：JWT + bcrypt，租户 ID 由 token 携带、
依赖注入强制生效——所有租户层查询必须经 CurrentUser.tenant_id 过滤。"""

import re
import time
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def validate_password(password: str) -> str | None:
    """密码强度校验：不合格返回中文原因，合格返回 None。注册/建号/重置密码统一使用。"""
    if len(password) < 8:
        return "密码至少 8 位"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "密码需同时包含字母和数字"
    return None


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user_id: int, tenant_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "role": role,
        "exp": datetime.now(UTC) + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


class CurrentUser:
    def __init__(self, user_id: int, tenant_id: int, role: str):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role


# 停用校验结果缓存：token 有效期内也要让停用生效，但不能每个请求都查库。
# 多进程部署下各进程独立缓存，停用最迟 TTL 秒后全面生效。
_BLOCK_CACHE_TTL = 60.0
_block_cache: dict[int, tuple[float, str | None]] = {}


def account_block_reason(user_id: int) -> str | None:
    """用户或所属租户被停用时返回中文原因，正常返回 None。"""
    hit = _block_cache.get(user_id)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]

    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models import Tenant, User

    with session_scope() as session:
        row = session.execute(
            select(User.enabled, Tenant.enabled)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(User.id == user_id)
        ).first()
    if row is None:
        reason = "用户不存在"
    elif not row[0]:
        reason = "账号已停用"
    elif not row[1]:
        reason = "企业账户已停用"
    else:
        reason = None
    _block_cache[user_id] = (now + _BLOCK_CACHE_TTL, reason)
    return reason


def clear_block_cache(user_id: int | None = None) -> None:
    """管理操作后主动失效缓存（仅当前进程；其他进程靠 TTL 过期）。"""
    if user_id is None:
        _block_cache.clear()
    else:
        _block_cache.pop(user_id, None)


def get_current_user(request: Request) -> CurrentUser:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"])
        current = CurrentUser(int(payload["sub"]), int(payload["tenant_id"]), payload["role"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录已过期") from exc
    if reason := account_block_reason(current.user_id):
        raise HTTPException(status_code=401, detail=reason)
    return current


CurrentUserDep = Depends(get_current_user)

ADMIN_ROLES = ("tenant_admin", "platform_admin")


def require_admin(current: CurrentUser = CurrentUserDep) -> CurrentUser:
    if current.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current


AdminDep = Depends(require_admin)


def require_platform_admin(current: CurrentUser = CurrentUserDep) -> CurrentUser:
    if current.role != "platform_admin":
        raise HTTPException(status_code=403, detail="需要平台管理员权限")
    return current


PlatformAdminDep = Depends(require_platform_admin)
