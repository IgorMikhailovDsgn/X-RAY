"""fix datasets.chk_datasets_sizes to include size_test (Phase 5c)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27

В исходной схеме (`docs/brainscan_schema.sql`) chk_datasets_sizes требует
`size_total = size_train + size_val`. Phase 5a добавил `size_test` (70/20/10
split), но я забыл обновить CHECK — это всплыло на Phase 5c при первом
реальном INSERT'е.

Меняем формулу. На dev и в тестах сейчас 0 datasets row, поэтому DROP+CREATE
безопасен.
"""

from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("chk_datasets_sizes", "datasets", type_="check")
    op.create_check_constraint(
        "chk_datasets_sizes",
        "datasets",
        "size_total = size_train + size_val + size_test",
    )


def downgrade() -> None:
    op.drop_constraint("chk_datasets_sizes", "datasets", type_="check")
    op.create_check_constraint(
        "chk_datasets_sizes",
        "datasets",
        "size_total = size_train + size_val",
    )
