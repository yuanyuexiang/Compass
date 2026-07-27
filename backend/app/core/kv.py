"""系统设置读写（system_settings 键值表）。"""

from sqlalchemy.orm import Session

from app.models import SystemSetting

KEY_CRAWL_INTERVAL = "crawl_interval_minutes"
KEY_LAST_AUTO_CRAWL = "last_auto_crawl_at"
DEFAULT_CRAWL_INTERVAL_MINUTES = 30

# 每租户每日 LLM 配额（0 或负数 = 不限）；超额走降级路径而非报错，见各调用点
KEY_QUOTA_NL_SEARCH = "quota_nl_search_daily"
KEY_QUOTA_PROFILE_SUGGEST = "quota_profile_suggest_daily"
KEY_QUOTA_MATCH = "quota_match_daily"
DEFAULT_QUOTA_NL_SEARCH = 50
DEFAULT_QUOTA_PROFILE_SUGGEST = 10
DEFAULT_QUOTA_MATCH = 300


def get_setting(session: Session, key: str, default=None):
    row = session.get(SystemSetting, key)
    return row.value if row is not None and row.value is not None else default


def set_setting(session: Session, key: str, value) -> None:
    row = session.get(SystemSetting, key)
    if row is None:
        session.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
