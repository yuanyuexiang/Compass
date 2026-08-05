from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# 幂等小迁移：create_all 不会给已存在的表加列，Alembic 引入前的过渡方案。
# 只允许 ADD COLUMN IF NOT EXISTS 这类可重复执行的语句。
MIGRATIONS = [
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS display_name VARCHAR(128)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(128)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(32)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'",
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS source_ids JSONB "
    "NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'",
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS created_by_tenant_id BIGINT",
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS reject_reason TEXT",
    "ALTER TABLE announcements ADD COLUMN IF NOT EXISTS biddable BOOLEAN",
    "ALTER TABLE match_results ADD COLUMN IF NOT EXISTS score_details JSONB "
    "NOT NULL DEFAULT '{}'::jsonb",
    # 存量清洗（幂等）：注册时首尾空格（含全角）入库导致登录失败；已有同名去空格行则跳过防撞唯一键
    "UPDATE users SET username = btrim(username, ' 　') "
    "WHERE username <> btrim(username, ' 　') "
    "AND NOT EXISTS (SELECT 1 FROM users x WHERE x.username = btrim(users.username, ' 　'))",
    "UPDATE tenants SET name = btrim(name, ' 　') "
    "WHERE name <> btrim(name, ' 　') "
    "AND NOT EXISTS (SELECT 1 FROM tenants x WHERE x.name = btrim(tenants.name, ' 　'))",
    # 平台租户（幂等）：platform_admin 账号统一挂靠到独立平台租户，不再混在业务租户里。
    # 没有平台租户则创建一个，再把所有 platform_admin 挪过去（新库/存量库通用）。
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_platform BOOLEAN NOT NULL DEFAULT FALSE",
    "INSERT INTO tenants (name, enabled, status, is_platform) "
    "SELECT '平台运营', TRUE, 'active', TRUE "
    "WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE is_platform) "
    "ON CONFLICT (name) DO UPDATE SET is_platform = TRUE, enabled = TRUE, status = 'active'",
    "UPDATE users SET tenant_id = (SELECT id FROM tenants WHERE is_platform ORDER BY id LIMIT 1) "
    "WHERE role = 'platform_admin' "
    "AND EXISTS (SELECT 1 FROM tenants WHERE is_platform) "
    "AND tenant_id NOT IN (SELECT id FROM tenants WHERE is_platform)",
]


def init_db() -> None:
    """建表 + 幂等迁移（schema 稳定后改用 Alembic）。"""
    import app.models  # noqa: F401  确保模型已注册

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        for stmt in MIGRATIONS:
            conn.execute(text(stmt))
        conn.commit()
