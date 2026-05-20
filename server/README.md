# brainscan-server

FastAPI backend для BrainScan. Phase A: scaffolding с применённой схемой БД. Phase B: реализация эндпоинтов из `shared/openapi.yaml`.

## Setup

```bash
cd server
uv sync
cp .env.example .env       # отредактировать секреты
```

## Локальный запуск

```bash
# 1. Поднять зависимости из корня репозитория
cd .. && docker compose up -d postgres redis minio minio-init

# 2. Применить миграции
cd server && uv run alembic upgrade head

# 3. Запустить API
uv run uvicorn app.main:app --reload --port 8000
```

Документация Swagger: http://localhost:8000/api/v1/docs

## Структура

```
server/
├── app/
│   ├── main.py          # FastAPI entry, роутеры подключаются в Phase B
│   ├── config.py        # pydantic-settings из .env
│   ├── db.py            # async SQLAlchemy session
│   ├── api/v1/          # роутеры (заполняются в Phase B)
│   ├── auth/            # JWT, Argon2
│   ├── storage/         # boto3 S3-обёртка
│   ├── ml/              # Celery таски (train trigger, dataset build)
│   ├── models/          # SQLAlchemy ORM модели
│   └── schemas/         # Pydantic DTO
├── alembic/
│   └── versions/
│       └── 0001_initial.py   # docs/brainscan_schema.sql + users table
└── tests/
```

## Миграции

Первая миграция применяет `docs/brainscan_schema.sql` целиком + добавляет `users` (для JWT-auth, в исходной схеме её не было).

```bash
uv run alembic upgrade head        # применить
uv run alembic downgrade base      # откатить всё (dev only)
uv run alembic revision -m "msg"   # новая миграция
```

Последующие миграции — стандартный alembic-стиль (`op.create_table`, `op.add_column` и т.п.). Не используем autogenerate в первой миграции, потому что схема пришла из готового SQL.
