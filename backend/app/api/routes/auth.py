from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.db import session_scope
from app.core.ratelimit import clear_login_failures, login_locked, record_login_failure
from app.core.security import (
    CurrentUser,
    CurrentUserDep,
    create_token,
    hash_password,
    validate_password,
    verify_password,
)
from app.models import Subscription, Tenant, User

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=128)
    username: str = Field(min_length=2, max_length=64)
    password: str
    email: str | None = Field(default=None, max_length=128)


def _user_info(user: User, tenant_name: str) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant_name,
    }


@router.post("/auth/register")
def register(body: RegisterIn) -> dict:
    """审批制开通：创建待审批租户 + 租户管理员账号，平台管理员通过后方可登录。"""
    if reason := validate_password(body.password):
        raise HTTPException(status_code=422, detail=reason)
    with session_scope() as session:
        if session.scalar(select(Tenant.id).where(Tenant.name == body.tenant_name)):
            raise HTTPException(status_code=409, detail="该企业名称已注册")
        if session.scalar(select(User.id).where(User.username == body.username)):
            raise HTTPException(status_code=409, detail="该用户名已被占用")
        tenant = Tenant(name=body.tenant_name, enabled=False, status="pending")
        session.add(tenant)
        session.flush()
        session.add(
            User(
                tenant_id=tenant.id,
                username=body.username,
                password_hash=hash_password(body.password),
                role="tenant_admin",
                email=body.email,
            )
        )
        session.add(Subscription(tenant_id=tenant.id))
        return {"message": "申请已提交，请等待平台管理员审批", "tenant_id": tenant.id}


@router.post("/auth/login")
def login(body: LoginIn) -> dict:
    if login_locked(body.username):
        raise HTTPException(status_code=429, detail="失败次数过多，请 10 分钟后再试")
    with session_scope() as session:
        user = session.scalar(select(User).where(User.username == body.username))
        if user is None or not verify_password(body.password, user.password_hash):
            record_login_failure(body.username)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user.enabled:
            raise HTTPException(status_code=403, detail="账号已停用，请联系企业管理员")
        tenant = session.get(Tenant, user.tenant_id)
        if tenant.status == "pending":
            raise HTTPException(status_code=403, detail="企业开通申请审批中，请耐心等待")
        if not tenant.enabled:
            raise HTTPException(status_code=403, detail="企业账户已停用，请联系平台管理员")
        clear_login_failures(body.username)
        return {
            "access_token": create_token(user.id, user.tenant_id, user.role),
            "user": _user_info(user, tenant.name),
        }


@router.get("/me")
def me(current: CurrentUser = CurrentUserDep) -> dict:
    with session_scope() as session:
        user = session.get(User, current.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="用户不存在")
        tenant = session.get(Tenant, user.tenant_id)
        return _user_info(user, tenant.name)
