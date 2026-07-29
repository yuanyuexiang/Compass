"""LLM 调用配置：直接使用 LiteLLM，不自研封装层（tech-design.md §3，已确认）。

- 模型经 settings 配置（默认 deepseek-v4-flash；旧模型名 2026-07-24 弃用，勿用）。
- 每次调用记账到 llm_usage 表（配额判断与商业化计费的底账），失败只告警不影响业务。
- M2 在 app/ai/extract.py 中实现字段提取与分类，Prompt 放 app/ai/prompts/。
"""

import logging

import litellm

from app.core.config import settings

logger = logging.getLogger(__name__)


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
    if not type(exc).__module__.startswith("litellm"):
        return None
    text = str(exc)
    if "Insufficient Balance" in text or "insufficient_quota" in text:
        return "AI 服务余额不足，请联系平台管理员为 DeepSeek 账户充值"
    if "rate" in text.lower() and "limit" in text.lower():
        return "AI 服务繁忙（限流），请稍后重试"
    if "api key" in text.lower() or type(exc).__name__ == "AuthenticationError":
        return "AI 服务密钥无效，请联系平台管理员检查配置"
    if "timeout" in text.lower():
        return "AI 服务响应超时，请稍后重试"
    return "AI 服务暂时不可用，请稍后重试"


def extract_completion(
    messages: list[dict], scene: str = "unknown", tenant_id: int | None = None, **kwargs
):
    """LLM 统一入口：JSON 输出 + 空返回重试由调用方负责。scene/tenant_id 用于用量记账。

    连续失败数与最近报错记入 Redis，供系统健康面板与告警使用（欠费/密钥失效即时可见）。
    """
    from datetime import UTC, datetime

    from app.core.ratelimit import counter_incr, counter_reset, note_set

    try:
        resp = litellm.completion(
            model=settings.llm_extract_model,
            api_key=settings.deepseek_api_key,
            messages=messages,
            response_format={"type": "json_object"},
            **kwargs,
        )
    except Exception as exc:
        counter_incr("llm_failures")
        note_set(
            "llm_last_error",
            f"{datetime.now(UTC).strftime('%m-%d %H:%M')} [{scene}] {str(exc)[:180]}",
        )
        raise
    counter_reset("llm_failures")
    _record_usage(scene, tenant_id, resp)
    return resp
