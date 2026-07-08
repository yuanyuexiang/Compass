import json
from types import SimpleNamespace

from app.ai import suggest as suggest_mod
from app.ai.suggest import compact_html, suggest_list_selectors

RAW = """
<html><head><style>.x{}</style><script>var a=1</script></head>
<body>
<nav class="top-nav"><a href="/">首页</a></nav>
<ul class="news-list">
  <li><a href="/1.html" title="招标公告一" data-x="junk">招标公告一</a>
      <span class="date">2026-07-08</span></li>
</ul>
<img src="/logo.png"/>
</body></html>
"""


def test_compact_html_strips_noise_keeps_structure():
    out = compact_html(RAW)
    assert "<script" not in out and "<style" not in out and "<img" not in out
    assert "news-list" in out  # class 保留
    assert "data-x" not in out  # 无关属性剔除
    assert 'href="/1.html"' in out  # href 保留


def fake_resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_suggest_list_selectors_filters_empty(monkeypatch):
    payload = {"item_selector": "ul.news-list li", "link_selector": "a", "date_selector": ""}
    monkeypatch.setattr(
        suggest_mod, "extract_completion", lambda **kw: fake_resp(json.dumps(payload))
    )
    result = suggest_list_selectors(RAW)
    assert result["item_selector"] == "ul.news-list li"
    assert result["link_selector"] == "a"
    assert "date_selector" not in result  # 空串被过滤，不写入 config
