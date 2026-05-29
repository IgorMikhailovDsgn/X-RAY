# syntax=docker/dockerfile:1.7
# BrainScan ML worker — Celery worker + beat scheduler. uv-managed Python 3.12.
# Build context = repo root (для единообразия с server/Dockerfile).
# Phase 6 (real training): сюда добавятся torch/ultralytics/opencv — нужен отдельный
# тяжёлый image. Сейчас минимальная сборка под Celery-таски-заглушки.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /app
COPY ml/pyproject.toml ml/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY ml/ ./
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

# CPU-worker: слушает ТОЛЬКО очередь `default` (retrain_trigger, maintenance).
# Тяжёлые train-таски маршрутизируются в `gpu` (см. celery_app.task_routes) и
# исполняются отдельным GPU-worker'ом (Dockerfile.gpu). `-B` = beat scheduler,
# живёт здесь (один на весь кластер).
CMD ["celery", "-A", "workers.celery_app", "worker", "-B", "-Q", "default", "--loglevel=info"]
