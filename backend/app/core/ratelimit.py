"""登录限流与每日配额（Redis 计数）。

Redis 不可用时一律放行并告警——护栏不应成为可用性单点；配额日界按北京时间。
"""

import logging
from datetime import datetime, timedelta, timezone

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 600

_TZ_BEIJING = timezone(timedelta(hours=8))
_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.redis_url, socket_timeout=2, socket_connect_timeout=2
        )
    return _client


def login_locked(username: str) -> bool:
    try:
        value = _redis().get(f"login_fail:{username}")
        return value is not None and int(value) >= LOGIN_MAX_FAILURES
    except redis.RedisError:
        logger.warning("Redis 不可用，登录限流跳过")
        return False


def record_login_failure(username: str) -> None:
    try:
        client = _redis()
        key = f"login_fail:{username}"
        if client.incr(key) == 1:
            client.expire(key, LOGIN_LOCK_SECONDS)
    except redis.RedisError:
        logger.warning("Redis 不可用，登录失败未计数")


def clear_login_failures(username: str) -> None:
    try:
        _redis().delete(f"login_fail:{username}")
    except redis.RedisError:
        pass


def acquire_cooldown(key: str, seconds: int) -> bool:
    """冷却闸：seconds 内首次调用返回 True，期间再调返回 False。
    Redis 不可用时放行（护栏不做单点）。用于画像重评估等防抖场景。"""
    try:
        return bool(_redis().set(f"cooldown:{key}", "1", nx=True, ex=seconds))
    except redis.RedisError:
        logger.warning("Redis 不可用，冷却检查跳过（%s）", key)
        return True


def counter_incr(key: str, ttl: int = 259_200) -> None:
    """通用递增计数（如 LLM 连续失败数），Redis 不可用时静默跳过。"""
    try:
        client = _redis()
        if client.incr(f"counter:{key}") == 1:
            client.expire(f"counter:{key}", ttl)
    except redis.RedisError:
        pass


def counter_reset(key: str) -> None:
    try:
        _redis().delete(f"counter:{key}")
    except redis.RedisError:
        pass


def counter_get(key: str) -> int:
    try:
        return int(_redis().get(f"counter:{key}") or 0)
    except redis.RedisError:
        return 0


def note_set(key: str, value: str, ttl: int = 259_200) -> None:
    """短便签（如最近一次 LLM 报错摘要），供健康面板展示。"""
    try:
        _redis().set(f"note:{key}", value, ex=ttl)
    except redis.RedisError:
        pass


def note_get(key: str) -> str | None:
    try:
        v = _redis().get(f"note:{key}")
        return v.decode() if v is not None else None
    except redis.RedisError:
        return None


def quota_key(scene: str, tenant_id: int, now: datetime | None = None) -> str:
    day = (now or datetime.now(_TZ_BEIJING)).astimezone(_TZ_BEIJING).strftime("%Y%m%d")
    return f"quota:{scene}:{tenant_id}:{day}"


def try_consume_quota(tenant_id: int, scene: str, limit: int) -> bool:
    """当日用量 +1；超限返回 False 由调用方降级。limit<=0 视为不限量。"""
    if limit <= 0:
        return True
    try:
        client = _redis()
        key = quota_key(scene, tenant_id)
        count = client.incr(key)
        if count == 1:
            client.expire(key, 172_800)  # 两天后自清，跨日界安全
        return count <= limit
    except redis.RedisError:
        logger.warning("Redis 不可用，配额检查跳过（场景 %s）", scene)
        return True
