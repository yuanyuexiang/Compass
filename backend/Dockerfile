FROM python:3.12-slim

# 经 PyPI 安装 uv（ghcr.io 在部分网络环境不可达）
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
