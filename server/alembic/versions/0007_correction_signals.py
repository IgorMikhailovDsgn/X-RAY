"""correction signals: weights, IoU, correction_type + detection confidence

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-15

Добавляет поля для weighted training:

* `localize_annotations` и `tumor_annotations`:
  - `correction_type` TEXT NULL — категория ошибки модели (FN/FP/WL/IB/MA или
    NULL для confirmed/cold-start).
  - `iou_with_detection` FLOAT NULL — IoU между detection и итоговой
    разметкой; хранится denormalized для аналитики.
  - `training_weight` FLOAT NOT NULL DEFAULT 1.0 — финальный множитель loss.
    Существующие 365 localize и 299 tumor аннотаций получают 1.0 — они уже
    зарезервированы в датасеты, в будущие тренировки не попадут, бэкфилл не
    нужен.

* `localize_detections` и `tumor_detections`:
  - `confidence` FLOAT NULL — уверенность модели на момент инференса.
    Nullable: исторические детекции значения не имеют.

* `chk_loc_ann_action_combinations` пере-RELAX-ится: branch `corrected` больше
  не требует `bbox IS NOT NULL`. Это разрешает FP-сигнал для локализатора
  («модель нашла регион, врач говорит — ничего нет»). tumor-таблица уже
  релакснута с миграции 0006.
"""

from __future__ import annotations

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


_LOC_RELAXED_V2 = """
    (action = 'confirmed' AND detection_id IS NOT NULL)
    OR
    (action = 'corrected' AND detection_id IS NOT NULL)
    OR
    (action = 'created'   AND detection_id IS NULL)
"""

# Тот же, что в 0006: требует bbox у corrected.
_LOC_RELAXED_V1 = """
    (action = 'confirmed' AND detection_id IS NOT NULL)
    OR
    (action = 'corrected' AND detection_id IS NOT NULL AND bbox IS NOT NULL)
    OR
    (action = 'created'   AND detection_id IS NULL)
"""


_VALID_CORRECTION_TYPES = (
    "'false_negative'",
    "'false_positive'",
    "'wrong_location'",
    "'imprecise_bbox'",
    "'minor_adjustment'",
)
_CORRECTION_TYPE_CHECK = (
    "correction_type IS NULL OR correction_type IN ("
    + ", ".join(_VALID_CORRECTION_TYPES)
    + ")"
)


def _add_correction_fields(table: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN correction_type TEXT NULL"
    )
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN iou_with_detection DOUBLE PRECISION NULL"
    )
    op.execute(
        f"ALTER TABLE {table} "
        "ADD COLUMN training_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0"
    )
    op.create_check_constraint(
        f"chk_{_short(table)}_correction_type",
        table,
        _CORRECTION_TYPE_CHECK,
    )
    op.create_check_constraint(
        f"chk_{_short(table)}_iou_range",
        table,
        "iou_with_detection IS NULL OR (iou_with_detection >= 0 "
        "AND iou_with_detection <= 1)",
    )
    op.create_check_constraint(
        f"chk_{_short(table)}_weight_positive",
        table,
        "training_weight > 0",
    )
    op.execute(
        f"CREATE INDEX idx_{_short(table)}_correction_type "
        f"ON {table}(correction_type) WHERE correction_type IS NOT NULL"
    )


def _drop_correction_fields(table: str) -> None:
    op.execute(
        f"DROP INDEX IF EXISTS idx_{_short(table)}_correction_type"
    )
    op.drop_constraint(f"chk_{_short(table)}_weight_positive", table, type_="check")
    op.drop_constraint(f"chk_{_short(table)}_iou_range", table, type_="check")
    op.drop_constraint(f"chk_{_short(table)}_correction_type", table, type_="check")
    op.execute(f"ALTER TABLE {table} DROP COLUMN training_weight")
    op.execute(f"ALTER TABLE {table} DROP COLUMN iou_with_detection")
    op.execute(f"ALTER TABLE {table} DROP COLUMN correction_type")


def _add_detection_confidence(table: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN confidence DOUBLE PRECISION NULL"
    )
    op.create_check_constraint(
        f"chk_{_short(table)}_confidence_range",
        table,
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )


def _drop_detection_confidence(table: str) -> None:
    op.drop_constraint(f"chk_{_short(table)}_confidence_range", table, type_="check")
    op.execute(f"ALTER TABLE {table} DROP COLUMN confidence")


def _short(table: str) -> str:
    # Короткие префиксы для индексов/чек'ов: укладываемся в PG identifier limit (63).
    return {
        "localize_annotations": "loc_ann",
        "tumor_annotations": "tum_ann",
        "localize_detections": "loc_det",
        "tumor_detections": "tum_det",
    }[table]


def upgrade() -> None:
    # Annotations.
    _add_correction_fields("localize_annotations")
    _add_correction_fields("tumor_annotations")

    # Detections.
    _add_detection_confidence("localize_detections")
    _add_detection_confidence("tumor_detections")

    # Relax localize chk_loc_ann_action_combinations: corrected больше не требует
    # bbox. FP-сигнал для локализатора теперь хранится честно.
    op.drop_constraint(
        "chk_loc_ann_action_combinations",
        "localize_annotations",
        type_="check",
    )
    op.create_check_constraint(
        "chk_loc_ann_action_combinations",
        "localize_annotations",
        _LOC_RELAXED_V2,
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_loc_ann_action_combinations",
        "localize_annotations",
        type_="check",
    )
    op.create_check_constraint(
        "chk_loc_ann_action_combinations",
        "localize_annotations",
        _LOC_RELAXED_V1,
    )

    _drop_detection_confidence("tumor_detections")
    _drop_detection_confidence("localize_detections")
    _drop_correction_fields("tumor_annotations")
    _drop_correction_fields("localize_annotations")
