"""LLM 调用配置：直接使用 LiteLLM，不自研封装层（tech-design.md §3，已确认）。

- 模型经 settings 配置（默认 deepseek-v4-flash；旧模型名 2026-07-24 弃用，勿用）。
- 用量统计走 litellm success_callback（M2 接成本报表）。
- M2 在 app/ai/extract.py 中实现字段提取与分类，Prompt 放 app/ai/prompts/。
"""

import litellm

from app.core.config import settings


def track_usage(kwargs, completion_response, start_time, end_time):  # noqa: ARG001
    """按环节/租户记录 token 用量（M2 落库，先打日志占位）。"""
    usage = getattr(completion_response, "usage", None)
    if usage:
        litellm.print_verbose(f"llm usage: {usage}")


litellm.success_callback = [track_usage]


def extract_completion(messages: list[dict], **kwargs):
    """AI 理解环节统一入口：JSON 输出 + 空返回重试由调用方（M2 extract.py）负责。"""
    return litellm.completion(
        model=settings.llm_extract_model,
        api_key=settings.deepseek_api_key,
        messages=messages,
        response_format={"type": "json_object"},
        **kwargs,
    )
