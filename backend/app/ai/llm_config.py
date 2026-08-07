"""LLM 调用配置：直接使用 LiteLLM，不自研封装层（tech-design.md §3，已确认）。

- 模型/密钥读取平台管理员在「模型服务」页的配置（system_settings，60 秒进程缓存，
  改动即时生效无需重启）；未配置默认模型时明确报错，不再回退环境变量密钥。
- 支持按场景（extract/match/nl_search/...）指定不同模型；主模型失败自动切备用（fallback）。
- 每次调用记账到 llm_usage 表（配额判断与商业化计费的底账），失败只告警不影响业务。
"""

import logging

import litellm

from app.core.config import settings

logger = logging.getLogger(__name__)


class LlmConfigurationError(RuntimeError):
    """平台尚未配置可用的模型供应商或默认模型。"""

# 已知 OpenAI 兼容供应商的官方端点。历史配置可能只保存了供应商名和 Key，Base URL
# 为空时不能让 LiteLLM 误回退到 api.openai.com。
KNOWN_PROVIDER_BASE_URLS = {
    "mimo": "https://api.xiaomimimo.com/v1",
}


def provider_base_url(name: str, configured: str | None) -> str | None:
    return (configured or "").strip() or KNOWN_PROVIDER_BASE_URLS.get(name)


def _load_llm_config() -> dict:
    """读平台配置（providers/scene_models/fallback），密钥已解密。DB 不可用返回空配置。

    每次调用直接读取，确保 API 保存后所有 Celery worker 立即看到新配置；LLM 网络耗时
    远大于这次轻量主键查询，不值得用无法跨进程失效的本地缓存换取错误配置风险。
    """
    cfg: dict = {"providers": {}, "scene_models": {}, "fallback": None}
    try:
        from app.core.crypto import decrypt
        from app.core.db import session_scope
        from app.core.kv import (
            KEY_LLM_FALLBACK,
            KEY_LLM_PROVIDERS,
            KEY_LLM_SCENE_MODELS,
            get_setting,
        )

        with session_scope() as session:
            for p in get_setting(session, KEY_LLM_PROVIDERS, []) or []:
                key = decrypt(p.get("api_key") or "")
                if p.get("name") and key:
                    cfg["providers"][p["name"]] = {
                        "api_key": key,
                        "base_url": provider_base_url(p["name"], p.get("base_url")),
                    }
            cfg["scene_models"] = get_setting(session, KEY_LLM_SCENE_MODELS, {}) or {}
            cfg["fallback"] = get_setting(session, KEY_LLM_FALLBACK, None)
    except Exception:  # noqa: BLE001  调用阶段会用清晰错误提示，不在加载阶段拖垮进程
        logger.warning("LLM 平台配置读取失败", exc_info=True)
    return cfg


def invalidate_llm_config_cache() -> None:
    """兼容现有保存调用；配置已改为每次实时读取，无本地缓存需要清理。"""


def resolve_llm_target(cfg: dict, scene: str) -> dict:
    """场景 → {model, api_key, base_url}。优先场景映射，其次 default 映射，最后 .env。"""
    entry = (cfg.get("scene_models") or {}).get(scene) or (cfg.get("scene_models") or {}).get(
        "default"
    )
    if entry:
        provider = (cfg.get("providers") or {}).get(entry.get("provider") or "")
        if provider and entry.get("model"):
            return {
                "model": entry["model"],
                "api_key": provider["api_key"],
                "base_url": provider["base_url"],
            }
    raise LlmConfigurationError("请先在平台“模型服务”中配置供应商和默认模型")


def resolve_llm_fallback(cfg: dict) -> dict | None:
    fb = cfg.get("fallback")
    if not fb:
        return None
    provider = (cfg.get("providers") or {}).get(fb.get("provider") or "")
    if provider and fb.get("model"):
        return {
            "model": fb["model"], "api_key": provider["api_key"], "base_url": provider["base_url"],
        }
    return None


def _record_usage(scene: str, tenant_id: int | None, response) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    try:
        from app.core.db import session_scope
        from app.models import LlmUsage

        with session_scope() as session:
            session.add(
                LlmUsage(
                    tenant_id=tenant_id,
                    scene=scene,
                    model=getattr(response, "model", "") or settings.llm_extract_model,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                )
            )
    except Exception:  # noqa: BLE001  记账失败不能拖垮业务调用
        logger.warning("LLM 用量落库失败（scene=%s）", scene, exc_info=True)


def friendly_llm_error(exc: Exception) -> str | None:
    """LLM 供应商异常 → 用户可读的中文提示；非 LLM 异常返回 None（调用方自行处理）。

    历史教训：DeepSeek 欠费时原始报错 `litellm.BadRequestError: ... Insufficient Balance`
    直接透给了终端用户。用户界面只该出现可行动的中文提示，原始异常记日志。
    """
    if isinstance(exc, LlmConfigurationError):
        return str(exc)
    if not type(exc).__module__.startswith("litellm"):
        return None
    text = str(exc)
    if "Insufficient Balance" in text or "insufficient_quota" in text:
        return "AI 服务余额不足，请联系平台管理员为 DeepSeek 账户充值"
    if "rate" in text.lower() and "limit" in text.lower():
        return "AI 服务繁忙（限流），请稍后重试"
    if "api key" in text.lower() or type(exc).__name__ == "AuthenticationError":
        return "AI 服务鉴权失败，请检查 API Key 是否有效，以及是否与当前 Base URL 配套"
    if any(
        marker in text.lower()
        for marker in ("model_not_found", "model not found", "invalid model", "does not exist")
    ):
        return "该模型不存在或当前账户无权使用，请检查供应商的模型列表"
    if "timeout" in text.lower():
        return "AI 服务响应超时，请稍后重试"
    return "AI 服务暂时不可用，请稍后重试"


def normalize_model_for_target(target: dict) -> str:
    """自定义 Base URL 均约定为 OpenAI 兼容端点，自动选择 LiteLLM 的 openai 适配器。

    管理员只需填写供应商公布的原始模型 ID；已有 ``openai/`` 配置保持不变。
    """
    model = str(target["model"]).strip()
    if target.get("base_url") and not model.startswith("openai/"):
        return f"openai/{model}"
    return model


def _call(target: dict, messages: list[dict], **kwargs):
    extra = {"api_base": target["base_url"]} if target.get("base_url") else {}
    return litellm.completion(
        model=normalize_model_for_target(target),
        api_key=target["api_key"],
        messages=messages,
        response_format={"type": "json_object"},
        **extra,
        **kwargs,
    )


def extract_completion(
    messages: list[dict],
    scene: str = "unknown",
    tenant_id: int | None = None,
    model_override: dict | None = None,
    **kwargs,
):
    """LLM 统一入口：JSON 输出 + 空返回重试由调用方负责。scene/tenant_id 用于用量记账。

    模型按场景解析（平台配置优先，.env 兜底）；主模型异常且配置了备用模型时自动切换
    重试一次。连续失败数与最近报错记入 Redis，供系统健康面板与告警使用。
    model_override（评测/测试连接用）：{model, api_key, base_url} 直接指定，跳过场景解析。
    """
    from datetime import UTC, datetime

    from app.core.ratelimit import counter_incr, counter_reset, note_delete, note_set

    cfg = _load_llm_config()
    target = model_override or resolve_llm_target(cfg, scene)
    # 流水线背压只关心字段提取是否可用。管理端测试、画像或自然语言搜索不应污染或
    # 清除自动提取的连败状态，否则“测试了另一个供应商”也会造成虚假恢复。
    track_pipeline_health = scene == "extract"
    try:
        resp = _call(target, messages, **kwargs)
    except Exception as exc:
        if track_pipeline_health:
            counter_incr("llm_failures")
            note_set(
                "llm_last_error",
                f"{datetime.now(UTC).strftime('%m-%d %H:%M')} [{scene}] {str(exc)[:180]}",
            )
        fallback = None if model_override else resolve_llm_fallback(cfg)
        # 备用与主完全相同（模型+密钥都一样）才放弃——同模型不同供应商 key 是合法备份
        if not fallback or (
            fallback["model"] == target["model"] and fallback["api_key"] == target["api_key"]
        ):
            raise
        logger.warning(
            "主模型 %s 调用失败，切换备用 %s（scene=%s）", target["model"], fallback["model"], scene
        )
        resp = _call(fallback, messages, **kwargs)
        note_set(
            "llm_fallback_last",
            f"{datetime.now(UTC).strftime('%m-%d %H:%M')} [{scene}] {target['model']} → "
            f"{fallback['model']}",
        )
        try:  # 运行日志（尽力而为，DB 故障不影响 LLM 主链路）
            from app.core.audit import record_event
            from app.core.db import session_scope

            with session_scope() as s:
                record_event(
                    s, "llm.fallback",
                    f"主模型 {target['model']} 失败，"
                    f"已切换备用 {fallback['model']}（场景 {scene}）",
                    level="warning",
                )
        except Exception:  # noqa: BLE001
            logger.debug("llm.fallback 事件记录失败", exc_info=True)
    if track_pipeline_health:
        counter_reset("llm_failures")
        note_delete("llm_last_error")
    _record_usage(scene, tenant_id, resp)
    return resp
