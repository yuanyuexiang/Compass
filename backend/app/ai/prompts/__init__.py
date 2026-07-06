"""Prompt 版本化管理：修改 Prompt 时新增版本常量并更新 CURRENT，勿原地改旧版本
（评测集回归对比需要，见 tech-design.md §10.2）。"""

from app.ai.prompts.extract_v1 import EXTRACT_SYSTEM_PROMPT_V1

EXTRACT_SYSTEM_PROMPT = EXTRACT_SYSTEM_PROMPT_V1
EXTRACT_PROMPT_VERSION = "v1"

__all__ = ["EXTRACT_PROMPT_VERSION", "EXTRACT_SYSTEM_PROMPT"]
