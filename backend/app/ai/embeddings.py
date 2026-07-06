"""向量化：bge-m3（经 SiliconFlow 等 OpenAI 兼容 API，tech-design.md §13 决策点 2）。

未配置 SILICONFLOW_API_KEY 时 available() 为 False，流水线跳过向量化直接发布，
匹配引擎退化为「规则过滤 + LLM 精排」二级漏斗——功能完整，召回面稍宽。
"""

import litellm

from app.core.config import settings

SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"


def available() -> bool:
    return bool(settings.siliconflow_api_key)


def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = litellm.embedding(
        model=settings.embedding_model,
        api_key=settings.siliconflow_api_key,
        api_base=SILICONFLOW_BASE,
        input=texts,
    )
    return [item["embedding"] for item in resp.data]
