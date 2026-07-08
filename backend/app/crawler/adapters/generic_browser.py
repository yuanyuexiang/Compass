"""通用动态网站适配器：与 generic 相同的选择器配置，但用 Playwright 渲染 JS 后再解析。

面向 JS 动态渲染的招标站点（列表/正文由前端脚本生成，httpx 拿不到）。
config 字段与 generic 完全一致，额外支持：
    wait_selector  可选，渲染后等待该元素出现再取 HTML（比 networkidle 更可靠）

注意（tech-design §4.1）：能渲染 JS 的普通动态站适用；带强反爬（验证码、瑞数 JS 挑战等）
的站点可能仍无法采集，需逐站专门处理。浏览器渲染开销大，仅在 httpx 拿不到数据时使用。
"""

from app.crawler.adapters.generic import GenericAdapter
from app.crawler.base import register


@register
class GenericBrowserAdapter(GenericAdapter):
    name = "generic_browser"
    display_name = "通用网站（动态渲染 / JS）"

    def _text(self, url: str) -> str:
        # 父类的 list_announcements / fetch_detail 都经 self._text 取页面，覆盖此处即改为浏览器渲染
        return self.render(url, wait_selector=self.config.get("wait_selector"))
