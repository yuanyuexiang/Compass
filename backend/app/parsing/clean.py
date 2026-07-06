"""清洗模块：详情页 HTML → 干净正文（tech-design.md §4.2）。"""

import re

from bs4 import BeautifulSoup

_BLANK_RE = re.compile(r"\n{3,}")


def html_to_text(html: str, selectors: list[str] | None = None) -> str:
    """提取正文纯文本。

    优先用适配器提供的正文选择器；都未命中时降级为 body 全文（去导航噪声能力弱，
    但保证有产出，低质量文本靠 LLM 阶段的 evidence 校验兜底）。
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    node = None
    for sel in selectors or []:
        node = soup.select_one(sel)
        if node is not None:
            break
    if node is None:
        node = soup.body or soup

    lines = [line.strip() for line in node.get_text("\n").splitlines()]
    text = "\n".join(line for line in lines if line)
    return _BLANK_RE.sub("\n\n", text).strip()
