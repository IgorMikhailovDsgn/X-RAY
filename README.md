# BrainScan

Сервис распознавания опухолей головного мозга по КТ/МРТ снимкам, открытым в DICOM-вьюверах на рабочих станциях специалистов.

Фоновое приложение захватывает скриншоты, специалист размечает область снимка (Region) и опухоль (Tumor), данные накапливаются на сервере для дообучения двух каскадных моделей: **локализатора** области снимка и **детектора опухоли** на crop'е области.

## Monorepo layout

```
brainscan/
├── docs/             # спецификации (annotation mode, metrics, DB schema)
├── shared/           # source-of-truth контракты (OpenAPI)
├── server/           # FastAPI + PostgreSQL + S3 + Celery
├── ml/               # MLflow, тренировочные воркеры, dataset builders
├── client-macos/     # Swift/SwiftUI клиент (menubar + overlay)
└── docker-compose.yml  # локальный dev-стек
```

## MVP scope

- macOS-клиент: ручная разметка (Annotate) с multi-bbox / multi-monitor / offline-очередью
- Сервер: auth, endpoints для скриншотов и аннотаций, S3-аплоад
- ML-инфраструктура поднята, **моделей нет** — Detect-кнопка в клиенте disabled до первой prod-модели
- Без автозахвата, без Windows-клиента, без подписи/нотаризации

Подробный план — `docs/plan.md` (если перенесён) либо обратиться к approved plan в `~/.claude/plans/`.

## Локальный запуск

### Вариант 1 — нативно (быстрый dev-loop с `--reload`)

```bash
docker compose up -d postgres redis minio mlflow      # инфра-сервисы
cd server
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

В отдельном терминале:
```bash
cd ml && uv sync && uv run celery -A workers.celery_app worker -B
```

### Вариант 2 — всё в Docker

```bash
docker compose up --build
```

Compose сам прогонит миграции (one-shot сервис `migrate`) и поднимет server + worker
поверх postgres/redis/minio. Полезно для проверки контейнерной сборки перед деплоем
в облако.

### Клиент

```bash
cd client-macos
xcodegen generate          # из project.yml
open BrainScan.xcodeproj
```
По умолчанию схема `BrainScan` собирается в Debug → `http://localhost:8000/api/v1`.
Для других сред есть конфигурации `Staging` и `Release` (см. ниже).

## Cloud deployment

Phase 1 (контейнеризация + multi-env) — см. план в `~/.claude/plans/twinkling-meandering-teacup.md`.

### Сборка образов

```bash
docker build -t brainscan/server:latest ./server
docker build -t brainscan/worker:latest ./ml
```

### Переменные окружения (server)

| Переменная | Обязательна | Описание |
|---|---|---|
| `APP_ENV` | да | `local` / `dev` / `stage` / `prod`. В non-local нет дефолтов для секретов. |
| `DATABASE_URL` | да | async-DSN: `postgresql+asyncpg://user:pwd@host/db` |
| `ALEMBIC_DATABASE_URL` | да | sync-DSN для миграций: `postgresql+psycopg2://...` |
| `JWT_SECRET` | да | 32+ байтa, генерируется `openssl rand -hex 32` |
| `S3_ENDPOINT_URL` | да | напр. `https://s3.timeweb.cloud` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | да | креды S3 |
| `S3_REGION` | нет | default `us-east-1` |
| `S3_BUCKET_SCREENSHOTS` / `_LOCALIZE` / `_MODELS` | нет | имена бакетов |
| `REDIS_URL` | да в non-local | broker для Celery |
| `LOG_LEVEL` | нет | default `INFO` |
| `CORS_DEV` | нет | `true` запрещён в non-local |

### Миграции в облаке

```bash
# Запускается отдельным one-shot джобом ДО старта server / worker:
docker run --rm \
  -e ALEMBIC_DATABASE_URL=postgresql+psycopg2://... \
  brainscan/server:latest \
  alembic upgrade head
```
Locally — то же через `docker compose run --rm migrate`.

### macOS-клиент — переключение среды

URL API хранится в `Info.plist` (ключ `BrainScanAPIBaseURL`), значение подставляется
из build-настройки `BRAINSCAN_API_BASE_URL` per-config (см. [client-macos/project.yml](client-macos/project.yml)).

```bash
xcodebuild ... -configuration Debug      # → http://localhost:8000/api/v1
xcodebuild ... -configuration Staging    # → stage URL
xcodebuild ... -configuration Release    # → prod URL
```

Реальные stage/prod URL'ы подставляем после поднятия сред в TimeWebCloud.

## Документация

| Файл | Содержание |
|---|---|
| `docs/brainscan_annotation_mode.md` | Полная спецификация UI режима разметки, состояния, валидация, action mapping |
| `docs/brainscan_metrics.md` | Метрики моделей: precision/recall/F1, специфика медицинского контекста, критерии продвижения в prod |
| `docs/brainscan_schema.sql` | Схема PostgreSQL: screenshots, detections, annotations, MLOps-таблицы |
