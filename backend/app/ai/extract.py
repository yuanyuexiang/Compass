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
MAX_INPUT_CHARS = 30_000  # 超长正文先截断（政采公告正文通常 <5K 字；map-reduce 摘要留 M2 后期）


class ExtractionError(RuntimeError):
    pass


def build_input(title: str, clean_text: str, attachment_texts: list[str] | None = None) -> str:
    parts = [f"【公告标题】{title}", "【公告正文】", clean_text]
    for i, text in enumerate(attachment_texts or [], 1):
        parts.append(f"【附件{i}正文】")
        parts.append(text)
    return "\n".join(parts)[:MAX_INPUT_CHARS]


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
            )
            content = resp.choices[0].message.content
            if not content or not content.strip():
                raise ExtractionError("LLM 返回空 content")
            return ExtractionResult.model_validate_json(content)
        except (ValidationError, ExtractionError, ValueError) as exc:
            last_error = exc
            logger.warning("提取失败（第 %d/%d 次）: %s", attempt, MAX_ATTEMPTS, exc)
    raise ExtractionError(f"连续 {MAX_ATTEMPTS} 次提取失败: {last_error}")
