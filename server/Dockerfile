# syntax=docker/dockerfile:1.7
# BrainScan FastAPI app — multi-stage, uv-managed Python 3.12.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /app

# Сначала только манифесты — кэш слоя переиспользуется, пока зависимости не меняются.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Исходники + установка проекта в .venv.
COPY . .
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# curl нужен только для HEALTHCHECK. Сами Python-пакеты (psycopg2-binary, argon2-cffi)
# уже self-contained, системные библиотеки не требуются.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь.
RUN useradd --create-home --shell /bin/bash --uid 1000 app
WORKDIR /app
COPY --from=builder /app /app
RUN chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
