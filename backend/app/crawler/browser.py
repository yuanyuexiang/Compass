"""Playwright 浏览器渲染基础设施（tech-design.md §4.1 的「Playwright 兜底」）。

用于 JS 动态渲染的招标站点：httpx 拿不到数据时，用真浏览器执行 JS 后取 HTML。
另提供网络拦截「探路」：抓出页面自身调用的 XHR/JSON 接口，摸清后往往可降级回 httpx 直连。

设计要点：
- 同步 Playwright API（与 Celery 同步 worker 一致）；进程内懒加载、复用同一浏览器实例。
- 优雅降级：未安装 playwright 或未装浏览器时 available() 为 False，调用 render() 抛清晰错误，
  由流水线按失败处理，不影响 httpx 类源站。
- FastAPI（异步上下文）中若要调用，须放线程池执行（见 api/routes/sources 的 inspect）。
"""

import logging
import threading
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright  # noqa: F401

    PLAYWRIGHT_IMPORTED = True
except ImportError:  # 依赖未安装
    PLAYWRIGHT_IMPORTED = False

_lock = threading.Lock()
_pw = None  # sync_playwright 上下文管理器实例
_browser = None  # 复用的浏览器实例


def available() -> bool:
    """playwright 包是否可导入（浏览器二进制是否就绪在首次 render 时才知道）。"""
    return PLAYWRIGHT_IMPORTED


def _get_browser():
    global _pw, _browser
    if _browser is not None:
        return _browser
    if not PLAYWRIGHT_IMPORTED:
        raise RuntimeError("未安装 playwright，无法使用浏览器渲染（pip install playwright）")
    with _lock:
        if _browser is None:
            _pw = sync_playwright().start()
            _browser = _pw.chromium.launch(
                headless=settings.playwright_headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            logger.info("Playwright chromium 已启动")
    return _browser


def _new_page():
    browser = _get_browser()
    context = browser.new_context(
        user_agent=settings.crawler_user_agent,
        ignore_https_errors=not settings.crawler_verify_ssl,
        viewport={"width": 1440, "height": 900},
    )
    return context


def render(url: str, wait_selector: str | None = None, timeout_s: float | None = None) -> str:
    """渲染页面执行 JS 后返回 HTML。wait_selector 指定则等该元素出现（更可靠）。"""
    timeout_ms = int((timeout_s or settings.browser_render_timeout) * 1000)
    context = _new_page()
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if wait_selector:
            # state=attached：元素进入 DOM 即可（抓取只需 HTML，不要求视觉可见，更稳）
            page.wait_for_selector(wait_selector, state="attached", timeout=timeout_ms)
        else:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        return page.content()
    finally:
        context.close()


_FETCH_JS = """async (a) => {
    try {
        const r = await fetch(a.url, {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(a.payload)});
        const t = await r.text();
        try { return {ok: true, json: JSON.parse(t)}; }
        catch (e) { return {ok: false, status: r.status, text: t.slice(0, 200)}; }
    } catch (e) { return {ok: false, error: String(e)}; }
}"""


def fetch_json_via_page(
    nav_url: str,
    api_url: str,
    payloads: list[dict],
    wait_selector: str | None = None,
    settle_s: float = 4.0,
    timeout_s: float | None = None,
) -> list[dict | None]:
    """先导航 nav_url 过 JS 挑战（瑞数类反爬），再在同一浏览器上下文里逐个 POST api_url 拿 JSON。

    用于接口型但被 JS 挑战保护的站点（如 jsggzy）：浏览器执行挑战脚本拿到通行 cookie 后，
    页面内 fetch 携带该 cookie 调数据接口即可放行。返回与 payloads 等长的结果列表，
    每项为 {ok, json} / {ok:false, ...}；单个失败为 None。
    """
    timeout_ms = int((timeout_s or settings.browser_render_timeout) * 1000)
    context = _new_page()
    try:
        page = context.new_page()
        page.goto(nav_url, wait_until="domcontentloaded", timeout=timeout_ms)
        if wait_selector:
            page.wait_for_selector(wait_selector, state="attached", timeout=timeout_ms)
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                pass  # 挑战页可能不进入 networkidle，靠下方 settle 兜底
        if settle_s:
            page.wait_for_timeout(int(settle_s * 1000))
        results: list[dict | None] = []
        for payload in payloads:
            try:
                results.append(page.evaluate(_FETCH_JS, {"url": api_url, "payload": payload}))
            except Exception as exc:
                logger.warning("fetch_json_via_page 单次失败: %s", exc)
                results.append(None)
        return results
    finally:
        context.close()


def discover_apis(url: str, timeout_s: float | None = None, max_apis: int = 40) -> list[dict]:
    """网络拦截「探路」：渲染页面并记录其发起的 XHR/fetch 请求（尤其返回 JSON 的），
    帮助摸清动态站点背后的数据接口，便于降级为 httpx 直连（tech-design.md §4.1）。"""
    timeout_ms = int((timeout_s or settings.browser_render_timeout) * 1000)
    calls: list[dict] = []
    seen: set[str] = set()
    context = _new_page()
    try:
        page = context.new_page()

        def on_response(resp):
            try:
                req = resp.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                ctype = resp.headers.get("content-type", "")
                if "json" not in ctype and "javascript" not in ctype:
                    return
                key = f"{req.method} {req.url.split('?')[0]}"
                if key in seen or len(calls) >= max_apis:
                    return
                seen.add(key)
                calls.append({
                    "method": req.method,
                    "url": req.url,
                    "resource_type": req.resource_type,
                    "content_type": ctype,
                    "status": resp.status,
                })
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        return calls
    finally:
        context.close()


def shutdown() -> None:
    """关闭浏览器（进程退出或 worker 回收时调用）。"""
    global _pw, _browser
    with _lock:
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _pw is not None:
            try:
                _pw.stop()
            except Exception:
                pass
            _pw = None


# 简单节流：浏览器渲染开销大，进程内串行 + 最小间隔
_last_render_at = 0.0


def throttle(min_interval: float) -> None:
    global _last_render_at
    wait = min_interval - (time.monotonic() - _last_render_at)
    if wait > 0:
        time.sleep(wait)
    _last_render_at = time.monotonic()
