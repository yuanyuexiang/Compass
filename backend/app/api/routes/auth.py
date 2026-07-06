from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.core.db import session_scope
from app.core.security import CurrentUser, CurrentUserDep, create_token, verify_password
from app.models import Tenant, User

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str
    password: str


def _user_info(user: User, tenant_name: str) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant_name,
    }


@router.post("/auth/login")
def login(body: LoginIn) -> dict:
    with session_scope() as session:
        user = session.scalar(select(User).where(User.username == body.username))
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        tenant = session.get(Tenant, user.tenant_id)
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
