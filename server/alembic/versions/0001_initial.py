"""initial schema: brainscan_schema.sql + users table

Revision ID: 0001
Revises:
Create Date: 2026-05-18

Source of truth: docs/brainscan_schema.sql (применяется as-is). Дополнительно
создаётся таблица users для JWT-аутентификации (в исходной схеме её нет, т.к.
изначально она проектировалась без модели прав доступа).
"""

from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


# docs/ лежит на 3 уровня выше: alembic/versions/0001_initial.py -> ../../../docs/
SCHEMA_SQL_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "brainscan_schema.sql"
)


USERS_TABLE_SQL = """
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    full_name       TEXT,
    role            TEXT NOT NULL DEFAULT 'annotator',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_users_role
        CHECK (role IN ('annotator', 'admin'))
);

CREATE INDEX idx_users_email ON users(email);
"""


def upgrade() -> None:
    schema_sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    # exec_driver_sql обходит парсер SQLAlchemy: в schema.sql есть
    # ":target_model_id" внутри SQL-комментариев, который op.execute()
    # принимает за bindparam и валится.
    bind = op.get_bind()
    bind.exec_driver_sql(schema_sql)
    bind.exec_driver_sql(USERS_TABLE_SQL)


def downgrade() -> None:
    # Полный сброс схемы. Используется только в dev — drop всех таблиц,
    # созданных в upgrade(), в порядке обратном зависимостям.
    op.get_bind().exec_driver_sql("""
        DROP TABLE IF EXISTS users CASCADE;
        DROP TABLE IF EXISTS tumor_annotations CASCADE;
        DROP TABLE IF EXISTS tumor_detections CASCADE;
        DROP TABLE IF EXISTS localize_images CASCADE;
        DROP TABLE IF EXISTS localize_annotations CASCADE;
        DROP TABLE IF EXISTS localize_detections CASCADE;
        DROP TABLE IF EXISTS screenshots CASCADE;
        DROP TABLE IF EXISTS deployments CASCADE;
        DROP TABLE IF EXISTS models CASCADE;
        DROP TABLE IF EXISTS datasets CASCADE;
    """)
