"""种子数据：演示租户（江苏建筑智能化/装修工程公司）+ 管理员账号 + 订阅。

设计意图：画像限定江苏省 → 规则过滤会拦掉外省公告；装修/智能化能力 →
LLM 精排应给苏州中学改造、工行支行改造高分，给监理/知产代理等低分。

用法：
    本地开发   uv run python scripts/dev_seed.py            # admin / admin123
    生产服务器 ADMIN_PASSWORD='强密码' docker compose -f docker-compose.prod.yml \
               --env-file .env run --rm --no-deps -e ADMIN_PASSWORD api \
               python scripts/dev_seed.py
"""

import os

from sqlalchemy import select

from app.core.db import init_db, session_scope
from app.core.security import hash_password
from app.matching.profiles import upsert_profile
from app.models import Source, Subscription, Tenant, User

SOURCES = [
    ("ccgp-zygg", "ccgp", "中国政府采购网·中央公告"),
    ("jsggzy", "jsggzy", "江苏省公共资源交易平台"),
]

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
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")

    init_db()
    with session_scope() as session:
        # 平台租户由 init_db 的幂等迁移保证存在；admin 挂靠于此，不混入业务租户
        platform = session.scalar(select(Tenant).where(Tenant.is_platform))
        if platform is None:
            platform = Tenant(name="平台运营", is_platform=True)
            session.add(platform)
            session.flush()

        tenant = session.scalar(select(Tenant).where(Tenant.name == PROFILE_DATA["name"]))
        if tenant is None:
            tenant = Tenant(name=PROFILE_DATA["name"])
            session.add(tenant)
            session.flush()
        upsert_profile(session, tenant.id, PROFILE_DATA)

        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            session.add(
                User(
                    tenant_id=platform.id,
                    username=username,
                    password_hash=hash_password(password),
                    role="platform_admin",  # 种子账号兼平台管理员：负责租户审批与用量报表
                )
            )
        else:
            user.password_hash = hash_password(password)  # 重跑可重置密码
            user.role = "platform_admin"  # 存量库回填平台管理员角色
            user.tenant_id = platform.id  # 存量库把 admin 挪到平台租户
        if session.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant.id)
        ) is None:
            session.add(Subscription(tenant_id=tenant.id, min_star=4))
        for name, adapter, display_name in SOURCES:
            source = session.scalar(select(Source).where(Source.name == name))
            if source is None:
                session.add(
                    Source(name=name, adapter=adapter, display_name=display_name, cron="0 * * * *")
                )
            elif not source.display_name:
                source.display_name = display_name  # 为存量数据回填中文名
        if password == "admin123":
            print("⚠ 使用默认密码 admin123（仅限本地开发；生产请设 ADMIN_PASSWORD）")
        print(f"平台租户就绪: #{platform.id} {platform.name}（管理员 {username}）")
        print(f"演示业务租户就绪: #{tenant.id} {tenant.name}")


if __name__ == "__main__":
    main()
