import pytest
from fastapi import HTTPException

from app.api.routes.sources import SourceIn, _adapters
from app.core.security import CurrentUser, require_admin


def test_registered_adapters_listed_with_chinese_names():
    adapters = _adapters()
    assert adapters["ccgp"] == "中国政府采购网"
    assert adapters["jsggzy"] == "江苏省公共资源交易平台"


def test_require_admin_allows_admin_roles():
    for role in ("tenant_admin", "platform_admin"):
        user = require_admin(CurrentUser(1, 1, role))
        assert user.role == role


def test_require_admin_rejects_sales():
    with pytest.raises(HTTPException) as exc:
        require_admin(CurrentUser(1, 1, "sales"))
    assert exc.value.status_code == 403


def test_source_in_validates_interval():
    with pytest.raises(ValueError):
        SourceIn(name="x", adapter="ccgp", min_interval_seconds=0.1)  # 低于 1 秒下限
    s = SourceIn(name="x", adapter="ccgp")
    assert s.min_interval_seconds == 3.0 and s.enabled is True
