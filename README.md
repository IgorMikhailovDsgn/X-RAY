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

```bash
docker compose up -d                                  # postgres, redis, minio, mlflow
cd server
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

В отдельном терминале:
```bash
cd ml && uv sync && uv run celery -A workers worker -B
```

Клиент:
```bash
open client-macos/BrainScan.xcodeproj
```

## Документация

| Файл | Содержание |
|---|---|
| `docs/brainscan_annotation_mode.md` | Полная спецификация UI режима разметки, состояния, валидация, action mapping |
| `docs/brainscan_metrics.md` | Метрики моделей: precision/recall/F1, специфика медицинского контекста, критерии продвижения в prod |
| `docs/brainscan_schema.sql` | Схема PostgreSQL: screenshots, detections, annotations, MLOps-таблицы |
