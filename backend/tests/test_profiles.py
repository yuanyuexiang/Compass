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


def test_tenant_watches_source():
    """租户「关注的数据源」判定：空列表 = 不限；否则要求命中（fan-out 与查询共用）。"""
    from app.matching.profiles import tenant_watches_source

    assert tenant_watches_source([], 5)
    assert tenant_watches_source([1, 5], 5)
    assert not tenant_watches_source([1, 2], 5)


def test_region_stem():
    """行政区划后缀剥离：省/市/自治区写法差异归一到地名主干。"""
    from app.matching.profiles import region_stem

    assert region_stem("江苏省") == "江苏"
    assert region_stem("北京市") == "北京"
    assert region_stem("广西壮族自治区") == "广西"
    assert region_stem("新疆维吾尔自治区") == "新疆"
    assert region_stem("内蒙古自治区") == "内蒙古"
    assert region_stem("江苏") == "江苏"  # 无后缀原样返回
    assert region_stem("市") == "市"  # 只剩后缀本身不剥（防空串）
