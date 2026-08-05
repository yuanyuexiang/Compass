from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.audit import client_ip, record_audit
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


def clean_username(v: str) -> str:
    """去首尾空白（含全角空格）；中间含空白直接拒绝。

    历史教训：注册时用户名带尾部空格（如「Johnson 」）入库，之后用「Johnson」永远登录失败。
    注册/建成员/登录三处统一经此清洗，登录侧顺带容忍用户误输的首尾空格。
    """
    v = v.strip()
    if any(ch.isspace() for ch in v):
        raise ValueError("用户名不能包含空格")
    return v


def clean_phone(v: str | None) -> str | None:
    phone = (v or "").strip()
    if not phone:
        return None
    if len(phone) > 32 or any(ch not in "+- 0123456789" for ch in phone):
        raise ValueError("手机号格式不正确")
    return phone


class LoginIn(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _clean(cls, v: str) -> str:
        return v.strip()  # 登录只去首尾空白，不因中间空格报错（报错文案会泄露规则）


class RegisterIn(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=128)
    username: str = Field(min_length=2, max_length=64)
    password: str
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("username")
    @classmethod
    def _clean_username(cls, v: str) -> str:
        return clean_username(v)

    @field_validator("tenant_name")
    @classmethod
    def _clean_tenant(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone")
    @classmethod
    def _clean_phone(cls, v: str | None) -> str | None:
        return clean_phone(v)


def _user_info(user: User, tenant_name: str) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "phone": user.phone,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant_name,
    }


@router.post("/auth/register")
def register(body: RegisterIn, request: Request) -> dict:
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
                phone=body.phone,
            )
        )
        session.add(Subscription(tenant_id=tenant.id))
        record_audit(
            session, None, "auth.register",
            target=f"tenant:{tenant.id} {tenant.name}",
            username=body.username, ip=client_ip(request),
        )
        return {"message": "申请已提交，请等待平台管理员审批", "tenant_id": tenant.id}


def _audit_login_failure(username: str, ip: str | None) -> None:
    """登录失败走独立事务落审计——主流程随即抛 401 会回滚外层 session。"""
    with session_scope() as session:
        record_audit(session, None, "auth.login_failed", username=username, ip=ip)


@router.post("/auth/login")
def login(body: LoginIn, request: Request) -> dict:
    ip = client_ip(request)
    if login_locked(body.username):
        _audit_login_failure(body.username, ip)
        raise HTTPException(status_code=429, detail="失败次数过多，请 10 分钟后再试")
    with session_scope() as session:
        user = session.scalar(select(User).where(User.username == body.username))
        if user is None or not verify_password(body.password, user.password_hash):
            record_login_failure(body.username)
            _audit_login_failure(body.username, ip)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user.enabled:
            raise HTTPException(status_code=403, detail="账号已停用，请联系企业管理员")
        tenant = session.get(Tenant, user.tenant_id)
        if tenant.status == "pending":
            raise HTTPException(status_code=403, detail="企业开通申请审批中，请耐心等待")
        if not tenant.enabled:
            raise HTTPException(status_code=403, detail="企业账户已停用，请联系平台管理员")
        clear_login_failures(body.username)
        record_audit(
            session, CurrentUser(user.id, user.tenant_id, user.role), "auth.login",
            username=user.username, ip=ip,
        )
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


class MeUpdateIn(BaseModel):
    email: str = ""
    phone: str = ""


@router.put("/me")
def update_me(body: MeUpdateIn, current: CurrentUser = CurrentUserDep) -> dict:
    """自助修改个人信息（用户名是登录标识不可改）。"""
    email = body.email.strip()
    try:
        phone = clean_phone(body.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if email and ("@" not in email or len(email) > 128):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    with session_scope() as session:
        user = session.get(User, current.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="用户不存在")
        user.email = email or None
        user.phone = phone or None
        record_audit(
            session, current, "me.update",
            detail={"email": email or None, "phone": phone},
        )
        tenant = session.get(Tenant, user.tenant_id)
        return _user_info(user, tenant.name)


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/me/password")
def change_my_password(body: PasswordChangeIn, current: CurrentUser = CurrentUserDep) -> dict:
    """自助改密码：验证原密码 + 新密码强度。改完旧登录态仍有效（JWT 无状态）。"""
    if reason := validate_password(body.new_password):
        raise HTTPException(status_code=422, detail=reason)
    with session_scope() as session:
        user = session.get(User, current.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="用户不存在")
        if not verify_password(body.old_password, user.password_hash):
            raise HTTPException(status_code=403, detail="原密码不正确")
        user.password_hash = hash_password(body.new_password)
        record_audit(session, current, "me.password_change")
    return {"ok": True}
