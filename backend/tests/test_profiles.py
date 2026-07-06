from app.matching.profiles import build_summary_text


def test_build_summary_text():
    text = build_summary_text(
        {
            "name": "测试公司",
            "description": "做智能化的",
            "products": ["安防监控", "综合布线"],
            "regions": ["江苏省"],
            "cases_text": "某中学改造项目",
        }
    )
    assert "企业名称: 测试公司" in text
    assert "主营产品: 安防监控、综合布线" in text
    assert "覆盖区域: 江苏省" in text
    assert "成功案例: 某中学改造项目" in text
    assert "合作品牌" not in text  # 空字段不输出
