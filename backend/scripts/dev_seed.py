"""种子数据：演示租户（江苏建筑智能化/装修工程公司）+ 管理员账号 + 订阅。

设计意图：画像限定江苏省 → 规则过滤会拦掉外省公告；装修/智能化能力 →
LLM 精排应给苏州中学改造、工行支行改造高分，给监理/知产代理等低分。

用法：uv run python scripts/dev_seed.py
"""

from sqlalchemy import select

from app.core.db import init_db, session_scope
from app.core.security import hash_password
from app.matching.profiles import upsert_profile
from app.models import Subscription, Tenant, User

PROFILE_DATA = {
    "name": "江苏智建工程科技有限公司",
    "description": "苏南地区建筑智能化与装饰装修工程服务商，专注学校、医院、金融网点的改造工程。",
    "products": ["安防监控系统", "综合布线", "机房工程", "楼宇自控"],
    "services": ["建筑智能化工程", "室内装饰装修工程", "机电安装", "弱电工程施工"],
    "industries": ["教育", "金融", "政府", "医疗"],
    "regions": ["江苏省"],
    "certifications": [
        "建筑装修装饰工程专业承包二级",
        "电子与智能化工程专业承包二级",
        "安全生产许可证",
    ],
    "brands": ["海康威视", "华为", "施耐德"],
    "cases_text": (
        "苏州工业园区某中学教学楼装修及智能化改造（680万元）\n"
        "南京某三甲医院门诊楼弱电改造（450万元）\n"
        "江苏某农商行营业网点装修工程年度框架（1200万元）"
    ),
    "filter": {"regions": ["江苏省"], "min_budget": 1000000},
}


def main() -> None:
    init_db()
    with session_scope() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.name == PROFILE_DATA["name"]))
        if tenant is None:
            tenant = Tenant(name=PROFILE_DATA["name"])
            session.add(tenant)
            session.flush()
        upsert_profile(session, tenant.id, PROFILE_DATA)

        if session.scalar(select(User).where(User.username == "admin")) is None:
            session.add(
                User(
                    tenant_id=tenant.id,
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role="tenant_admin",
                )
            )
        if session.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant.id)
        ) is None:
            session.add(Subscription(tenant_id=tenant.id, min_star=4))
        print(f"种子租户就绪: #{tenant.id} {tenant.name}（账号 admin / admin123）")


if __name__ == "__main__":
    main()
