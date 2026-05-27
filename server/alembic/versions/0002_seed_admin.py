"""seed admin role from ADMIN_SEED_EMAIL env-var

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27

Идемпотентная data-migration: если в окружении задан ADMIN_SEED_EMAIL и в БД
есть пользователь с таким email — проставляет ему role='admin'. Если такого
пользователя ещё нет (Igor не зарегистрировался), миграция тихо ничего не
делает; роль можно прокинуть руками через одноразовый UPDATE после регистрации.
"""

from __future__ import annotations

import os

from sqlalchemy import text

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    email = os.environ.get("ADMIN_SEED_EMAIL")
    if not email:
        return
    op.execute(
        text("UPDATE users SET role='admin' WHERE email=:email AND role <> 'admin'")
        .bindparams(email=email)
    )


def downgrade() -> None:
    # Откатывать сидинг небезопасно — может быть несколько админов.
    # Если действительно нужно — `UPDATE users SET role='annotator'` руками.
    pass
