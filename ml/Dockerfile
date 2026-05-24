# syntax=docker/dockerfile:1.7
# BrainScan ML worker — Celery worker + beat scheduler. uv-managed Python 3.12.
# Phase 6 (real training): сюда добавятся torch/ultralytics/opencv — нужен отдельный
# тяжёлый image. Сейчас минимальная сборка под Celery-таски-заглушки.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --shell /bin/bash --uid 1000 app
WORKDIR /app
COPY --from=builder /app /app
RUN chown -R app:app /app
USER app

# Worker + beat scheduler в одном контейнере (MVP, низкая нагрузка). В проде
# разнесём на отдельные deployment'ы, когда появятся реальные long-running таски.
CMD ["celery", "-A", "workers.celery_app", "worker", "-B", "--loglevel=info"]
