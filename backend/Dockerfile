FROM python:3.12-slim

# 经 PyPI 安装 uv（ghcr.io 在部分网络环境不可达）
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Playwright chromium + 系统依赖：供 JS 动态站采集（worker 用；api/beat 不用但共享镜像）。
# 显著增大镜像（约 +400MB）；若确定不采集动态站，可注释此行以瘦身。
RUN uv run playwright install --with-deps chromium

COPY app ./app
COPY scripts ./scripts

# PYTHONPATH 保证 `python scripts/xxx.py` 也能找到 app 包（uvicorn/celery 本就不依赖此项）
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
