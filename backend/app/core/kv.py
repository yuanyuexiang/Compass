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
# 自动采集只在时间窗内跑（AI 能处理才采集，夜间不采、不攒积压）。
AUTO_LLM_START_MINUTE = 7 * 60 + 30
AUTO_LLM_END_MINUTE = 22 * 60 + 30
AUTO_LLM_BACKLOG_BATCH = 20
# 自动 AI 提取时效：公告发布超过该时长（发布时间缺失按采集时间）仍未提取的
# 直接标 skipped 放弃——招投标公告有强时效性，过期公告提取只烧 token 没有商机
# 价值；新源灌入的历史公告也靠它整批拦下。手动触发不受此限制。
AUTO_EXTRACT_MAX_AGE_HOURS = 48
# 背压：待 AI 提取积压（时效内）达到该值时暂停自动采集，消化到阈值下自动恢复
# ——采集快于消化没有意义，积压从源头就不该形成。50 条 ≈ 12 分钟消化量，队列
# 常态接近零；单轮采集灌入几百条会临时冲过阈值，随后采集暂停直到消化回落。
# 手动采集不受限。
AUTO_CRAWL_MAX_PENDING = 50
# LLM 连续失败达该数（欠费/密钥失效等）视为"AI 处理不了"：自动采集与积压派发
# 暂停，仅留每 tick 一条探针试探恢复（任一 LLM 调用成功即清零计数、自动恢复满速）。
LLM_FAILURE_PAUSE_STREAK = 5

# 日志保留天数：操作日志（追责用途）留久些，运行日志（流水线事件）滚动清理
AUDIT_LOG_RETENTION_DAYS = 180
SYSTEM_EVENT_RETENTION_DAYS = 30

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
