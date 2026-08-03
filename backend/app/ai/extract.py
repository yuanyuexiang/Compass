"""AI 理解：字段提取 + 智能分类（tech-design.md §4.3）。

JSON 模式 + Pydantic 严格校验；DeepSeek 官方提示 JSON 模式偶发返回空 content，
以及可能返回不合法 JSON —— 统一在此重试（最多 MAX_ATTEMPTS 次），仍失败抛
ExtractionError，由流水线标记 failed 进人工队列。
"""

import logging

from pydantic import ValidationError

from app.ai.llm_config import extract_completion
from app.ai.prompts import EXTRACT_SYSTEM_PROMPT
from app.ai.schemas import ExtractionResult

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_BODY_CHARS = 12_000
MAX_ATTACHMENT_CHARS = 4_000
MAX_INPUT_CHARS = MAX_BODY_CHARS + MAX_ATTACHMENT_CHARS
MAX_OUTPUT_TOKENS = 1_400


class ExtractionError(RuntimeError):
    pass


def build_input(title: str, clean_text: str, attachment_texts: list[str] | None = None) -> str:
    parts = [f"【公告标题】{title}", "【公告正文】", clean_text[:MAX_BODY_CHARS]]
    attachment_budget = MAX_ATTACHMENT_CHARS
    for i, text in enumerate(attachment_texts or [], 1):
        if attachment_budget <= 0:
            break
        excerpt = text[:attachment_budget]
        parts.append(f"【附件{i}正文】")
        parts.append(excerpt)
        attachment_budget -= len(excerpt)
    return "\n".join(parts)


def extract_project(input_text: str) -> ExtractionResult:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = extract_completion(
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                    {"role": "user", "content": input_text},
                ],
                temperature=0.0,
                max_tokens=MAX_OUTPUT_TOKENS,
                scene="extract",
            )
            content = resp.choices[0].message.content
            if not content or not content.strip():
                raise ExtractionError("LLM 返回空 content")
            return ExtractionResult.model_validate_json(content)
        except (ValidationError, ExtractionError, ValueError) as exc:
            last_error = exc
            logger.warning("提取失败（第 %d/%d 次）: %s", attempt, MAX_ATTEMPTS, exc)
    raise ExtractionError(f"连续 {MAX_ATTEMPTS} 次提取失败: {last_error}")
