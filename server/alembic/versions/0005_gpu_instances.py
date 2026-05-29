"""gpu_instances table + gpu_autoscale_enabled setting (Phase 7b)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29

Под GPU auto-orchestration: таблица аудита/состояния провиженных GPU-инстансов
(Selectel OpenStack) + master-switch в system_settings.

gpu_instances.status lifecycle: provisioning → active → deleting → deleted
(или failed на любом этапе). Partial unique idx_one_live_gpu гарантирует не
более одного живого инстанса на провайдера — defence-in-depth поверх
reconcile-логики.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gpu_instances",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "provider", sa.String(), nullable=False, server_default=sa.text("'selectel'")
        ),
        sa.Column("openstack_server_id", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'provisioning'"),
        ),
        sa.Column("flavor", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('provisioning','active','deleting','deleted','failed')",
            name="chk_gpu_status",
        ),
    )
    # Не больше одного живого (provisioning|active) инстанса на провайдера.
    op.execute(
        "CREATE UNIQUE INDEX idx_one_live_gpu ON gpu_instances (provider) "
        "WHERE status IN ('provisioning','active')"
    )
    op.create_index(
        "idx_gpu_instances_created",
        "gpu_instances",
        [sa.text("created_at DESC")],
    )

    # Master-switch автоскейла — default false (opt-in, чтобы не жечь деньги).
    op.execute(
        """
        INSERT INTO system_settings (key, value)
        VALUES ('gpu_autoscale_enabled', 'false'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM system_settings WHERE key = 'gpu_autoscale_enabled'")
    op.drop_index("idx_gpu_instances_created", table_name="gpu_instances")
    op.execute("DROP INDEX IF EXISTS idx_one_live_gpu")
    op.drop_table("gpu_instances")
