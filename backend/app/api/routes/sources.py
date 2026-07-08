"""采集源管理：查看（登录即可）+ 增改/启停/手动触发（仅管理员）。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.db import session_scope
from app.core.security import AdminDep, CurrentUser, CurrentUserDep
from app.crawler.base import ADAPTERS
from app.models import Announcement, Source

router = APIRouter(prefix="/api")


def _adapters() -> dict[str, str]:
    """{注册名: 中文名}"""
    import app.crawler.adapters  # noqa: F401  触发注册

    return {name: cls.display_name or name for name, cls in sorted(ADAPTERS.items())}


def _source_out(s: Source, count: int) -> dict:
    adapters = _adapters()
    return {
        "id": s.id,
        "name": s.name,
        "display_name": s.display_name or s.name,
        "adapter": s.adapter,
        "adapter_display_name": adapters.get(s.adapter, s.adapter),
        "enabled": s.enabled,
        "min_interval_seconds": s.min_interval_seconds,
        "config": s.config or {},
        "last_run_at": s.last_run_at,
        "announcement_count": count,
    }


@router.get("/sources")
def list_sources(current: CurrentUser = CurrentUserDep) -> list[dict]:
    with session_scope() as session:
        counts = dict(
            session.execute(
                select(Announcement.source_id, func.count()).group_by(Announcement.source_id)
            ).all()
        )
        rows = session.scalars(select(Source).order_by(Source.id)).all()
        return [_source_out(s, counts.get(s.id, 0)) for s in rows]


@router.get("/sources/adapters")
def list_adapters(current: CurrentUser = CurrentUserDep) -> list[dict]:
    return [{"name": k, "display_name": v} for k, v in _adapters().items()]


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=128)
    adapter: str
    enabled: bool = True
    min_interval_seconds: float = Field(default=3.0, ge=1.0, le=60.0)
    config: dict = {}


class SourceUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    min_interval_seconds: float | None = Field(default=None, ge=1.0, le=60.0)
    config: dict | None = None


@router.post("/sources")
def create_source(body: SourceIn, current: CurrentUser = AdminDep) -> dict:
    if body.adapter not in _adapters():
        raise HTTPException(status_code=422, detail=f"未注册的适配器: {body.adapter}")
    with session_scope() as session:
        if session.scalar(select(Source).where(Source.name == body.name)):
            raise HTTPException(status_code=409, detail="同名数据源已存在")
        source = Source(
            name=body.name,
            display_name=body.display_name or body.name,
            adapter=body.adapter,
            enabled=body.enabled,
            min_interval_seconds=body.min_interval_seconds,
            config=body.config,
            cron="0 * * * *",
        )
        session.add(source)
        session.flush()
        return _source_out(source, 0)


@router.put("/sources/{source_id}")
def update_source(source_id: int, body: SourceUpdate, current: CurrentUser = AdminDep) -> dict:
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        if body.display_name is not None:
            source.display_name = body.display_name
        if body.enabled is not None:
            source.enabled = body.enabled
        if body.min_interval_seconds is not None:
            source.min_interval_seconds = body.min_interval_seconds
        if body.config is not None:
            source.config = body.config
        return {"ok": True}


@router.post("/sources/{source_id}/crawl")
def trigger_crawl(source_id: int, current: CurrentUser = AdminDep) -> dict:
    from app.tasks.pipeline import crawl_source_task

    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        if not source.enabled:
            raise HTTPException(status_code=422, detail="数据源已停用，请先启用")
    crawl_source_task.delay(source_id)
    return {"ok": True, "queued": True}


@router.post("/sources/crawl-all")
def trigger_crawl_all(current: CurrentUser = AdminDep) -> dict:
    from app.tasks.pipeline import crawl_all_sources

    crawl_all_sources.delay()
    return {"ok": True, "queued": True}
