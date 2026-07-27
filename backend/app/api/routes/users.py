"""租户内成员管理：tenant_admin 管理本租户账号。跨租户一律 404，防探测。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.db import session_scope
from app.core.security import (
    AdminDep,
    CurrentUser,
    clear_block_cache,
    hash_password,
    validate_password,
)
from app.models import User

router = APIRouter(prefix="/api/tenant/users")

ROLE_LABELS = {"platform_admin": "平台管理员", "tenant_admin": "企业管理员", "sales": "业务员"}
ASSIGNABLE_ROLES = ("tenant_admin", "sales")


class UserCreateIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str
    email: str | None = Field(default=None, max_length=128)
    role: str = "sales"


class UserPatchIn(BaseModel):
    role: str | None = None
    enabled: bool | None = None
    email: str | None = Field(default=None, max_length=128)


class ResetPasswordIn(BaseModel):
    password: str


def _user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "role_label": ROLE_LABELS.get(u.role, u.role),
        "email": u.email,
        "enabled": u.enabled,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _get_member(session, user_id: int, current: CurrentUser) -> User:
    user = session.get(User, user_id)
    if user is None or user.tenant_id != current.tenant_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    # 平台管理员账号不允许被租户管理员操作（其角色/停用只能由本人以外的平台管理员处理）
    if user.role == "platform_admin" and current.role != "platform_admin":
        raise HTTPException(status_code=403, detail="无权操作平台管理员账号")
    return user


@router.get("")
def list_users(current: CurrentUser = AdminDep) -> dict:
    with session_scope() as session:
        users = session.scalars(
            select(User).where(User.tenant_id == current.tenant_id).order_by(User.id)
        ).all()
        return {"items": [_user_out(u) for u in users], "total": len(users)}


@router.post("")
def create_user(body: UserCreateIn, current: CurrentUser = AdminDep) -> dict:
    if body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=422, detail="角色只能是企业管理员或业务员")
    if reason := validate_password(body.password):
        raise HTTPException(status_code=422, detail=reason)
    with session_scope() as session:
        if session.scalar(select(User.id).where(User.username == body.username)):
            raise HTTPException(status_code=409, detail="该用户名已被占用")
        user = User(
            tenant_id=current.tenant_id,
            username=body.username,
            password_hash=hash_password(body.password),
            role=body.role,
            email=body.email,
        )
        session.add(user)
        session.flush()
        return _user_out(user)


@router.patch("/{user_id}")
def patch_user(user_id: int, body: UserPatchIn, current: CurrentUser = AdminDep) -> dict:
    if body.role is not None and body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=422, detail="角色只能是企业管理员或业务员")
    with session_scope() as session:
        user = _get_member(session, user_id, current)
        if user.id == current.user_id and (body.enabled is False or body.role == "sales"):
            raise HTTPException(status_code=422, detail="不能停用或降级自己的账号")
        if body.role is not None and user.role != "platform_admin":
            user.role = body.role
        if body.enabled is not None:
            user.enabled = body.enabled
        if body.email is not None:
            user.email = body.email
        session.flush()
        result = _user_out(user)
    clear_block_cache(user_id)
    return result


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetPasswordIn, current: CurrentUser = AdminDep) -> dict:
    if reason := validate_password(body.password):
        raise HTTPException(status_code=422, detail=reason)
    with session_scope() as session:
        user = _get_member(session, user_id, current)
        user.password_hash = hash_password(body.password)
    return {"id": user_id, "message": "密码已重置"}
