"""MLOps dataset pipeline — schema (Phase 5a)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27

Закладывает таблицы и связи под полный pipeline формирования датасета (Phase 5):
- annotation FK в datasets (двухфазная пометка свободных vs зарезервированных аннотаций);
- расширение datasets под lifecycle (building→ready→training→completed|failed);
- audit-таблица dataset_builds с partial unique для защиты от параллельных запусков;
- training_candidates — очередь на админ-апрув в manual-режиме;
- system_settings — гибкий key/value для training_mode и будущих настроек.

Endpoint'ы (Phase 5b/c/d/e) и реализация builder/pipeline идут отдельными коммитами.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. dataset_id reservation FK на аннотациях --------------------------
    # NULL = аннотация свободна, доступна для нового dataset'а.
    # value = зарезервирована за конкретным dataset'ом.
    # При failed training делается UPDATE ... SET dataset_id=NULL → аннотации
    # возвращаются в пул.
    op.add_column(
        "localize_annotations",
        sa.Column("dataset_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_localize_annotations_dataset",
        "localize_annotations",
        "datasets",
        ["dataset_id"],
        ["id"],
    )
    op.create_index(
        "idx_localize_annotations_dataset",
        "localize_annotations",
        ["dataset_id"],
    )
    # Partial index — основной хот-путь "найти свободные аннотации".
    op.execute(
        "CREATE INDEX idx_localize_annotations_free "
        "ON localize_annotations (annotated_at) "
        "WHERE dataset_id IS NULL"
    )

    op.add_column(
        "tumor_annotations",
        sa.Column("dataset_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tumor_annotations_dataset",
        "tumor_annotations",
        "datasets",
        ["dataset_id"],
        ["id"],
    )
    op.create_index(
        "idx_tumor_annotations_dataset",
        "tumor_annotations",
        ["dataset_id"],
    )
    op.execute(
        "CREATE INDEX idx_tumor_annotations_free "
        "ON tumor_annotations (annotated_at) "
        "WHERE dataset_id IS NULL"
    )

    # ---- 2. datasets: lifecycle + аудит --------------------------------------
    # На dev сейчас 0 datasets, поэтому DEFAULT 'building' безопасен. Если бы
    # существующие были — их пришлось бы backfill'нуть статусом 'completed'.
    op.add_column(
        "datasets",
        sa.Column("size_test", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "datasets",
        sa.Column("stats", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "datasets",
        sa.Column(
            "status", sa.String(), nullable=False, server_default=sa.text("'building'")
        ),
    )
    op.add_column(
        "datasets",
        sa.Column(
            "approved_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_datasets_approved_by",
        "datasets",
        "users",
        ["approved_by"],
        ["id"],
    )
    op.add_column(
        "datasets",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "datasets", sa.Column("failed_reason", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        "chk_datasets_status",
        "datasets",
        "status IN ('building','ready','training','completed','failed')",
    )

    # ---- 3. dataset_builds (audit) -------------------------------------------
    op.create_table(
        "dataset_builds",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        # 'cron' | 'manual:{admin_user_id}' — текстом, потому что 'cron' не UUID.
        sa.Column("triggered_by", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),  # 'auto' | 'manual'
        sa.Column(
            "dataset_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "model_type IN ('localize','tumor')", name="chk_builds_model_type"
        ),
        sa.CheckConstraint(
            "status IN ('in_progress','completed','failed')", name="chk_builds_status"
        ),
    )
    # Partial unique — только один in_progress build на model_type. Защищает от
    # коллизий вне зависимости от advisory lock (defence-in-depth).
    op.execute(
        "CREATE UNIQUE INDEX idx_one_active_build "
        "ON dataset_builds (model_type) WHERE status = 'in_progress'"
    )
    op.create_index(
        "idx_dataset_builds_model",
        "dataset_builds",
        ["model_type", sa.text("started_at DESC")],
    )

    # ---- 4. training_candidates (manual mode queue) --------------------------
    # status сокращён до approval-only (pending/approved/skipped). Прогресс
    # обучения отслеживается через datasets.status (source of truth).
    op.create_table(
        "training_candidates",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("annotations_count", sa.Integer(), nullable=False),
        sa.Column("stats", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("gate_passed", sa.Boolean(), nullable=False),
        sa.Column("gate_issues", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column(
            "approved_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column(
            "dataset_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "model_type IN ('localize','tumor')", name="chk_candidates_model_type"
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','skipped')", name="chk_candidates_status"
        ),
    )
    op.create_index(
        "idx_training_candidates_status",
        "training_candidates",
        ["model_type", "status", sa.text("created_at DESC")],
    )

    # ---- 5. system_settings (flexible key/value) -----------------------------
    op.create_table(
        "system_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    # Дефолт: оба model_type в manual. Безопаснее, чем auto (никаких сюрпризов
    # при первом дальнейшем коммите) и удобнее, чем suspended (не блокирует
    # экспериментирование). Admin переключает PUT /admin/training/mode.
    op.execute(
        """
        INSERT INTO system_settings (key, value)
        VALUES ('training_mode',
                '{"localize": "manual", "tumor": "manual"}'::jsonb)
        """
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_index("idx_training_candidates_status", table_name="training_candidates")
    op.drop_table("training_candidates")
    op.drop_index("idx_dataset_builds_model", table_name="dataset_builds")
    op.execute("DROP INDEX IF EXISTS idx_one_active_build")
    op.drop_table("dataset_builds")

    op.drop_constraint("chk_datasets_status", "datasets", type_="check")
    op.drop_column("datasets", "failed_reason")
    op.drop_column("datasets", "approved_at")
    op.drop_constraint("fk_datasets_approved_by", "datasets", type_="foreignkey")
    op.drop_column("datasets", "approved_by")
    op.drop_column("datasets", "status")
    op.drop_column("datasets", "stats")
    op.drop_column("datasets", "size_test")

    op.execute("DROP INDEX IF EXISTS idx_tumor_annotations_free")
    op.drop_index("idx_tumor_annotations_dataset", table_name="tumor_annotations")
    op.drop_constraint(
        "fk_tumor_annotations_dataset", "tumor_annotations", type_="foreignkey"
    )
    op.drop_column("tumor_annotations", "dataset_id")

    op.execute("DROP INDEX IF EXISTS idx_localize_annotations_free")
    op.drop_index(
        "idx_localize_annotations_dataset", table_name="localize_annotations"
    )
    op.drop_constraint(
        "fk_localize_annotations_dataset", "localize_annotations", type_="foreignkey"
    )
    op.drop_column("localize_annotations", "dataset_id")
