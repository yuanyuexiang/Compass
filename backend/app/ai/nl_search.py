"""AI 自然语言搜索（tech-design.md §5.3）：LLM 解析口语查询为结构化 DSL。

解析失败时降级为关键词搜索，保证有结果。
"""

import json
import logging

from app.ai.llm_config import extract_completion
from app.ai.prompts.nl_search_v1 import NL_SEARCH_PROMPT_V1 as PARSE_PROMPT

logger = logging.getLogger(__name__)


def parse_query(query: str) -> dict:
    try:
        resp = extract_completion(
            messages=[
                {"role": "system", "content": PARSE_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
        )
        content = resp.choices[0].message.content
        filters = json.loads(content)
        if not isinstance(filters, dict):
            raise ValueError("非对象")
        return {k: v for k, v in filters.items() if v not in (None, "", [])}
    except Exception as exc:
        logger.warning("NL 查询解析失败，降级关键词: %s", exc)
        return {"keyword": query}
