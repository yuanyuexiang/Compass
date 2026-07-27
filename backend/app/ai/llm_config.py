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


def extract_completion(
    messages: list[dict], scene: str = "unknown", tenant_id: int | None = None, **kwargs
):
    """LLM 统一入口：JSON 输出 + 空返回重试由调用方负责。scene/tenant_id 用于用量记账。"""
    resp = litellm.completion(
        model=settings.llm_extract_model,
        api_key=settings.deepseek_api_key,
        messages=messages,
        response_format={"type": "json_object"},
        **kwargs,
    )
    _record_usage(scene, tenant_id, resp)
    return resp
