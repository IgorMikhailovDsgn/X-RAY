import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GpuInstance(Base):
    """Состояние и аудит провиженных GPU-инстансов (Phase 7b auto-orchestration).

    Lifecycle status: provisioning → active → deleting → deleted | failed.
    `last_activity_at` бампается reconcile'ом пока есть спрос (datasets в
    ready/training); idle-teardown считает от него. Partial unique
    idx_one_live_gpu (в миграции) держит ≤1 живой инстанс на провайдера.
    """

    __tablename__ = "gpu_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'selectel'")
    )
    openstack_server_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'provisioning'")
    )
    flavor: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
