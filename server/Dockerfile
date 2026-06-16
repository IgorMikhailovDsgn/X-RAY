# syntax=docker/dockerfile:1.7
# BrainScan FastAPI app — multi-stage, uv-managed Python 3.12.
# Build context = repo root (нужен docs/brainscan_schema.sql для alembic-миграции).

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /app

# Сначала только манифесты — кэш слоя переиспользуется, пока зависимости не меняются.
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Исходники + установка проекта в .venv.
COPY server/ ./
RUN uv sync --frozen --no-dev

# Inference deps для /detect (Phase 9, подход A — CPU torch прямо в server-образе).
# Отдельно от lock'а: torch CPU wheel index отличается от PyPI и кросс-платформенно
# не лочится надёжно. Веса yolov8n ~6MB, CPU-инференс на dev-VPS укладывается в сек.
RUN uv pip install --no-cache --python /app/.venv/bin/python \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        torch torchvision "ultralytics==8.4.*" opencv-python-headless pillow


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
# Schema-источник для миграции 0001_initial — она читает `/docs/brainscan_schema.sql`
# через Path(__file__).parents[3] / "docs" / ... (см. server/alembic/versions/0001_initial.py).
COPY docs/brainscan_schema.sql /docs/brainscan_schema.sql
RUN chown -R app:app /app /docs
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
