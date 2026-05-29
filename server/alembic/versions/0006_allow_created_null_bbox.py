"""allow action='created' with bbox NULL (cold-start negatives)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-29

Исходный CHECK требовал `created AND bbox IS NOT NULL` — это не давало создавать
negative-примеры (bbox NULL = «области/опухоли нет») в cold-start Annotate-флоу,
где модели ещё нет и единственный action — 'created'. Снимаем требование bbox у
ветки 'created' (detection_id IS NULL остаётся). confirmed/corrected — без
изменений.

DROP+CREATE безопасен: ни одной строки с created+bbox=NULL ещё нет (CHECK не
пускал), так что пересоздание не падает на существующих данных.
"""

from __future__ import annotations

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


_LOC_RELAXED = """
    (action = 'confirmed' AND detection_id IS NOT NULL)
    OR
    (action = 'corrected' AND detection_id IS NOT NULL AND bbox IS NOT NULL)
    OR
    (action = 'created'   AND detection_id IS NULL)
"""

_LOC_STRICT = """
    (action = 'confirmed' AND detection_id IS NOT NULL)
    OR
    (action = 'corrected' AND detection_id IS NOT NULL AND bbox IS NOT NULL)
    OR
    (action = 'created'   AND detection_id IS NULL AND bbox IS NOT NULL)
"""

_TUM_RELAXED = """
    (action = 'confirmed' AND detection_id IS NOT NULL)
    OR
    (action = 'corrected' AND detection_id IS NOT NULL)
    OR
    (action = 'created'   AND detection_id IS NULL)
"""

_TUM_STRICT = """
    (action = 'confirmed' AND detection_id IS NOT NULL)
    OR
    (action = 'corrected' AND detection_id IS NOT NULL)
    OR
    (action = 'created'   AND detection_id IS NULL AND bbox IS NOT NULL)
"""


def _swap(table: str, constraint: str, expr: str) -> None:
    op.drop_constraint(constraint, table, type_="check")
    op.create_check_constraint(constraint, table, expr)


def upgrade() -> None:
    _swap("localize_annotations", "chk_loc_ann_action_combinations", _LOC_RELAXED)
    _swap("tumor_annotations", "chk_tum_ann_action_combinations", _TUM_RELAXED)


def downgrade() -> None:
    _swap("localize_annotations", "chk_loc_ann_action_combinations", _LOC_STRICT)
    _swap("tumor_annotations", "chk_tum_ann_action_combinations", _TUM_STRICT)
