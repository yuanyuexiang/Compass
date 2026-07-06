from pathlib import Path

from app.parsing.clean import html_to_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_clean_ccgp_detail_with_selector():
    html = (FIXTURES / "ccgp_detail.html").read_text(encoding="utf-8")
    text = html_to_text(html, ["div.vF_detail_content"])
    assert len(text) > 800
    # 关键业务字段应在正文中（供 M2 LLM 提取）
    for keyword in ["项目名称", "项目编号", "采购预算", "3300万元", "2026年07月09日"]:
        assert keyword in text, f"缺少关键词: {keyword}"
    # 导航噪声不应混入
    assert "首页" not in text[:200]


def test_clean_fallback_to_body_without_selector():
    text = html_to_text("<html><body><p>你好</p><script>x=1</script></body></html>")
    assert text == "你好"
