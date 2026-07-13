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


# —— 测试采集（不入库的试跑预览，必须声明在 /{source_id} 路由之前）——


class SourceTestIn(BaseModel):
    adapter: str
    config: dict = {}


@router.post("/sources/test")
def test_source(body: SourceTestIn, current: CurrentUser = AdminDep) -> dict:
    """用给定配置试采列表前 5 条 + 首条详情正文，供保存前验证选择器。"""
    from app.crawler.base import get_adapter
    from app.parsing.clean import html_to_text

    if body.adapter not in _adapters():
        raise HTTPException(status_code=422, detail=f"未注册的适配器: {body.adapter}")
    config = dict(body.config)
    config.setdefault("min_interval_seconds", 1)  # 试跑只发 2 个请求，用短间隔
    adapter = get_adapter(body.adapter, config)
    try:
        items = []
        for raw in adapter.list_announcements():
            items.append(
                {
                    "title": raw.title,
                    "url": raw.url,
                    "publish_time": raw.publish_time.isoformat() if raw.publish_time else None,
                    "region": raw.region,
                }
            )
            if len(items) >= 5:
                break
        detail_preview = None
        if items:
            text = html_to_text(adapter.fetch_detail(items[0]["url"]), adapter.content_selectors())
            detail_preview = {"content_excerpt": text[:400], "content_length": len(text)}
        return {"ok": True, "items": items, "detail_preview": detail_preview}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "items": [], "detail_preview": None}
    finally:
        adapter.close()


# —— AI 自动识别（贴网址 → LLM 生成选择器 → 自动试采验证）——


# 已知专用适配器的域名（命中即用专用采集，最准）
DOMAIN_ADAPTERS = {
    "ccgp.gov.cn": "ccgp",
    "jsggzy.jszwfw.gov.cn": "jsggzy",
}


def _preview_items(raw_items: list) -> list[dict]:
    return [
        {
            "title": it.title,
            "url": it.url,
            "publish_time": it.publish_time.isoformat() if it.publish_time else None,
            "region": it.region,
        }
        for it in raw_items[:5]
    ]


class SmartSuggestIn(BaseModel):
    url: str = Field(min_length=8)


@router.post("/sources/smart-suggest")
def smart_suggest(body: SmartSuggestIn, current: CurrentUser = AdminDep) -> dict:
    """智能识别：贴网址 → 自动判定专用/静态/动态 → 生成配置 → 试采预览（tech-design §4.1）。

    ① 域名命中已知专用适配器 → 用专用采集；② 未知站点用 httpx 判静/动，动态走 Playwright 渲染；
    ③ LLM 生成选择器；④ 试采，静态 0 条自动转动态重试一次。
    """
    from urllib.parse import urlparse

    host = (urlparse(body.url).hostname or "").lower()
    for domain, adapter_name in DOMAIN_ADAPTERS.items():
        if host == domain or host.endswith("." + domain):
            return _smart_known(adapter_name, body.url)
    return _smart_generic(body.url)


def _smart_known(adapter_name: str, url: str) -> dict:
    """域名命中专用适配器：用其默认配置试采预览。"""
    from app.crawler.base import get_adapter
    from app.parsing.clean import html_to_text

    display = _adapters().get(adapter_name, adapter_name)
    adapter = get_adapter(adapter_name, {"min_interval_seconds": 1})
    try:
        items = []
        for raw in adapter.list_announcements():
            items.append(raw)
            if len(items) >= 5:
                break
        detail_preview = None
        if items:
            text = html_to_text(adapter.fetch_detail(items[0].url), adapter.content_selectors())
            detail_preview = {"content_excerpt": text[:400], "content_length": len(text)}
        return {
            "ok": bool(items),
            "adapter": adapter_name,
            "adapter_display_name": display,
            "config": {},
            "items": _preview_items(items),
            "detail_preview": detail_preview,
            "notes": f"识别为「{display}」专用采集",
            "error": None if items else "专用适配器本次未采到公告，请稍后重试或改用高级设置",
        }
    except Exception as exc:
        return {"ok": False, "adapter": adapter_name, "adapter_display_name": display,
                "config": {}, "items": [], "detail_preview": None,
                "notes": f"识别为「{display}」专用采集", "error": str(exc)[:400]}
    finally:
        adapter.close()


def _smart_generic(url: str) -> dict:
    """未知站点：httpx 判静/动 → 生成选择器 → 试采，静态 0 条转动态重试。"""
    from app.ai.suggest import looks_dynamic, suggest_config_and_items, suggest_content_selector
    from app.crawler import browser
    from app.crawler.base import get_adapter
    from app.parsing.clean import html_to_text

    def build(adapter_name: str, config: dict, items: list, note: str) -> dict:
        detail_preview = None
        if items:
            gen = get_adapter(adapter_name, {**config, "min_interval_seconds": 1})
            try:
                detail_html = gen.fetch_detail(items[0].url)
            finally:
                gen.close()
            if cs := suggest_content_selector(detail_html):
                text = html_to_text(detail_html, [cs])
                if len(text) >= 100:
                    config["content_selector"] = cs
                else:
                    text = html_to_text(detail_html)
            else:
                text = html_to_text(detail_html)
            detail_preview = {"content_excerpt": text[:400], "content_length": len(text)}
        ok = len(items) >= 3
        return {
            "ok": ok, "adapter": adapter_name,
            "adapter_display_name": _adapters().get(adapter_name, adapter_name),
            "config": config, "items": _preview_items(items), "detail_preview": detail_preview,
            "notes": note,
            "error": None if ok else "自动识别置信度不足，可在高级设置手动调整选择器后测试",
        }

    # ② httpx 取一次，判静/动
    dynamic = True
    html = ""
    hx = get_adapter("generic", {"list_url": url, "min_interval_seconds": 1})
    try:
        html = hx.get(url).text
        dynamic = looks_dynamic(html)
    except Exception:
        dynamic = True  # 取不到（超时/非200）按动态处理
    finally:
        hx.close()

    # ③④ 静态路线
    if not dynamic:
        config, items = suggest_config_and_items(html, url)
        if items:
            return build("generic", config, items, "识别为「通用网站（静态）」")
        # 静态 0 条 → 转动态重试（用户选的 A 兜底）

    # 动态路线：Playwright 渲染后再识别
    if not browser.available():
        return {"ok": False, "adapter": "generic_browser",
                "adapter_display_name": _adapters().get("generic_browser", "generic_browser"),
                "config": {"list_url": url}, "items": [], "detail_preview": None,
                "notes": "疑似动态站，但服务未安装浏览器",
                "error": "该站点需要动态渲染，但当前环境未安装 Playwright 浏览器"}
    try:
        rendered = browser.render(url)
    except Exception as exc:
        return {"ok": False, "adapter": "generic_browser",
                "adapter_display_name": _adapters().get("generic_browser", "generic_browser"),
                "config": {"list_url": url}, "items": [], "detail_preview": None,
                "notes": "动态渲染失败", "error": str(exc)[:400]}
    config, items = suggest_config_and_items(rendered, url)
    return build("generic_browser", config, items, "识别为「通用网站（动态渲染 / JS）」")


class SuggestIn(BaseModel):
    list_url: str = Field(min_length=8)


@router.post("/sources/suggest")
def suggest_source(body: SuggestIn, current: CurrentUser = AdminDep) -> dict:
    """用户只提供列表页网址：抓取 → LLM 识别选择器 → 试采验证 → 返回配置与预览。"""
    from app.ai.suggest import suggest_content_selector, suggest_list_selectors
    from app.crawler.adapters.generic import GenericAdapter
    from app.crawler.base import get_adapter
    from app.parsing.clean import html_to_text

    adapter = get_adapter("generic", {"list_url": body.list_url, "min_interval_seconds": 1})
    try:
        list_html = adapter.get(body.list_url).text

        selectors = suggest_list_selectors(list_html)
        config = {"list_url": body.list_url, **selectors}
        items = GenericAdapter.parse_list(list_html, body.list_url, config) if selectors else []
        if len(items) < 3:  # 置信度不足时带反馈重试一次
            fb = f"item_selector「{config.get('item_selector')}」只匹配到 {len(items)} 条公告"
            retry = suggest_list_selectors(list_html, feedback=fb)
            if retry:
                retry_config = {"list_url": body.list_url, **retry}
                retry_items = GenericAdapter.parse_list(list_html, body.list_url, retry_config)
                if len(retry_items) > len(items):
                    config, items = retry_config, retry_items

        detail_preview = None
        if items:
            detail_html = adapter.get(items[0].url).text
            if content_selector := suggest_content_selector(detail_html):
                text = html_to_text(detail_html, [content_selector])
                if len(text) >= 100:  # 选择器有效性验证
                    config["content_selector"] = content_selector
                else:
                    text = html_to_text(detail_html)
            else:
                text = html_to_text(detail_html)
            detail_preview = {"content_excerpt": text[:400], "content_length": len(text)}

        ok = len(items) >= 3
        return {
            "ok": ok,
            "config": config,
            "items": [
                {
                    "title": it.title,
                    "url": it.url,
                    "publish_time": it.publish_time.isoformat() if it.publish_time else None,
                    "region": it.region,
                }
                for it in items[:5]
            ],
            "detail_preview": detail_preview,
            "error": None if ok else "自动识别置信度不足，请核对下方选择器或手动调整后测试",
        }
    except Exception as exc:
        return {"ok": False, "config": None, "items": [], "detail_preview": None,
                "error": str(exc)[:500]}
    finally:
        adapter.close()


# —— 自动采集调度设置（必须声明在 /{source_id} 路由之前）——


class ScheduleIn(BaseModel):
    interval_minutes: int = Field(ge=5, le=720)  # 下限 5 分钟：对源站保持礼貌


@router.get("/sources/schedule")
def get_schedule(current: CurrentUser = CurrentUserDep) -> dict:
    from app.core.kv import (
        DEFAULT_CRAWL_INTERVAL_MINUTES,
        KEY_CRAWL_INTERVAL,
        KEY_LAST_AUTO_CRAWL,
        get_setting,
    )

    with session_scope() as session:
        return {
            "interval_minutes": get_setting(
                session, KEY_CRAWL_INTERVAL, DEFAULT_CRAWL_INTERVAL_MINUTES
            ),
            "last_auto_crawl_at": get_setting(session, KEY_LAST_AUTO_CRAWL),
        }


@router.put("/sources/schedule")
def put_schedule(body: ScheduleIn, current: CurrentUser = AdminDep) -> dict:
    from app.core.kv import KEY_CRAWL_INTERVAL, set_setting

    with session_scope() as session:
        set_setting(session, KEY_CRAWL_INTERVAL, body.interval_minutes)
    return {"ok": True, "interval_minutes": body.interval_minutes}


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
        # 防重复采集：同平台且采集配置完全相同的源只允许一个
        for existing in session.scalars(select(Source).where(Source.adapter == body.adapter)):
            if (existing.config or {}) == (body.config or {}):
                raise HTTPException(
                    status_code=409,
                    detail=f"与「{existing.display_name or existing.name}」同平台且配置相同，"
                    "会重复采集；如需拆分范围请修改 config",
                )
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


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, current: CurrentUser = AdminDep) -> dict:
    """仅允许删除没有公告数据的源；有数据的源出于完整性只能停用。"""
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        count = session.scalar(
            select(func.count()).select_from(Announcement).where(
                Announcement.source_id == source_id
            )
        )
        if count:
            raise HTTPException(
                status_code=409,
                detail=f"该数据源已采集 {count} 条公告，为保数据完整性不可删除，请改为停用",
            )
        session.delete(source)
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
