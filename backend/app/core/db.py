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
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'",
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS source_ids JSONB "
    "NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active'",
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS created_by_tenant_id BIGINT",
    "ALTER TABLE sources ADD COLUMN IF NOT EXISTS reject_reason TEXT",
    "ALTER TABLE announcements ADD COLUMN IF NOT EXISTS biddable BOOLEAN",
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
