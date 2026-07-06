"""认证与租户上下文（tech-design.md §10.3）：JWT + bcrypt，租户 ID 由 token 携带、
依赖注入强制生效——所有租户层查询必须经 CurrentUser.tenant_id 过滤。"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


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


def get_current_user(request: Request) -> CurrentUser:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"])
        return CurrentUser(int(payload["sub"]), int(payload["tenant_id"]), payload["role"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录已过期") from exc


CurrentUserDep = Depends(get_current_user)
