# brainscan-ml

Celery воркеры для дообучения моделей + интеграция с MLflow.

## Phase A scope

- Scaffolding Celery + beat-расписание
- Stub-таски тренировки (logging only, реальная тренировка отключена через `ENABLE_REAL_TRAINING=false`)
- Stub builder датасетов

## Запуск

```bash
cd ml
uv sync
cp .env.example .env

# worker + beat в одном процессе (для dev)
uv run celery -A workers.celery_app worker -B --loglevel=info
```

MLflow UI: http://localhost:5000 (поднимается через `docker compose up mlflow`).

## Структура

```
ml/
├── workers/
│   ├── celery_app.py       # Celery instance + beat schedule
│   ├── retrain_trigger.py  # ежесуточная проверка порога новых аннотаций
│   ├── train_localize.py   # stub в MVP, реальная тренировка в Phase E
│   └── train_tumor.py      # stub в MVP, реальная тренировка в Phase E
└── datasets/
    └── builder.py          # сборка манифеста из БД и заливка в S3 (stub)
```

## Когда добавлять реальные модели

После того как накопится первый размеченный датасет (~1000 аннотаций на тип). Тогда:
1. Добавить torch / ultralytics в `pyproject.toml`
2. Реализовать `datasets/builder.py` → манифест в S3, row в `datasets`
3. Реализовать `train_localize.train` / `train_tumor.train` → веса в S3, row в `models`
4. Установить `ENABLE_REAL_TRAINING=true`
5. (опционально) добавить автопромоут в prod по критериям из `docs/brainscan_metrics.md`
