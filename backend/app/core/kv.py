"""系统设置读写（system_settings 键值表）。"""

from sqlalchemy.orm import Session

from app.models import SystemSetting

KEY_CRAWL_INTERVAL = "crawl_interval_minutes"
# LLM 模型服务配置（平台管理员在「模型服务」页维护；api_key 经 core/crypto 加密存储）
KEY_LLM_PROVIDERS = "llm_providers"  # [{name, api_key(密文), base_url}]
KEY_LLM_SCENE_MODELS = "llm_scene_models"  # {default|extract|match|...: {provider, model}}
KEY_LLM_FALLBACK = "llm_fallback"  # {provider, model}，主模型失败自动切换
KEY_LAST_AUTO_CRAWL = "last_auto_crawl_at"
DEFAULT_CRAWL_INTERVAL_MINUTES = 30

# 自动 AI 流水线按北京时间运行。手动触发不受此限制。
# 时间窗和批量值先作为安全默认值集中维护，后续可在管理端开放配置。
AUTO_LLM_START_MINUTE = 7 * 60 + 30
AUTO_LLM_END_MINUTE = 22 * 60 + 30
NIGHT_CRAWL_INTERVAL_MINUTES = 240
AUTO_LLM_BACKLOG_BATCH = 20

# 每租户每日 LLM 配额（0 或负数 = 不限）；超额走降级路径而非报错，见各调用点
KEY_QUOTA_NL_SEARCH = "quota_nl_search_daily"
KEY_QUOTA_PROFILE_SUGGEST = "quota_profile_suggest_daily"
KEY_QUOTA_MATCH = "quota_match_daily"
DEFAULT_QUOTA_NL_SEARCH = 50
DEFAULT_QUOTA_PROFILE_SUGGEST = 10
# 精排是成本最高场景；默认按单租户每日约 100 次封顶，平台管理员仍可覆盖。
DEFAULT_QUOTA_MATCH = 100


def get_setting(session: Session, key: str, default=None):
    row = session.get(SystemSetting, key)
    return row.value if row is not None and row.value is not None else default


def set_setting(session: Session, key: str, value) -> None:
    row = session.get(SystemSetting, key)
    if row is None:
        session.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
