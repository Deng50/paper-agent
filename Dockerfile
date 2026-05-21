# 单镜像，api 与 frontend 共用（不同启动命令）。Python 3.12 + uv。
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# uv 官方镜像取二进制
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

WORKDIR /app

# 先装依赖（利用层缓存）：仅复制依赖清单
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# 再复制源码并安装项目本身
COPY . .
RUN uv sync --no-dev

EXPOSE 8000 8501

# 默认起 api；frontend 在 compose 里覆盖 command
CMD ["uvicorn", "lit_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
