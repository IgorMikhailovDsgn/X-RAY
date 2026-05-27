import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    size_total: Mapped[int] = mapped_column(Integer, nullable=False)
    size_train: Mapped[int] = mapped_column(Integer, nullable=False)
    size_val: Mapped[int] = mapped_column(Integer, nullable=False)
    # Phase 5a: 70/20/10 split — добавлен test-сет отдельной колонкой
    # (DEFAULT 0 для существующих строк, на dev их 0).
    size_test: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    manifest_path: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # Lifecycle: building→ready→training→completed|failed.
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'building'")
    )
    # Snapshot статистики на момент формирования — positive/negative/by_action и т.п.
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Кто и когда апрувнул (только manual-режим). NULL для auto.
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Заполняется при status='failed' для диагностики.
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class DatasetBuild(Base):
    """Audit-журнал запусков builder'а. Каждый POST /admin/datasets/build пишет
    сюда строку; partial unique индекс idx_one_active_build не даёт двум
    in_progress build'ам существовать одновременно для одного model_type
    (защита от коллизий, дополняет PG advisory lock).
    """

    __tablename__ = "dataset_builds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'in_progress'")
    )
    # 'cron' | 'manual:{admin_user_id}' — текст, потому что 'cron' не UUID.
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)  # 'auto' | 'manual'
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TrainingCandidate(Base):
    """Очередь на админ-апрув в manual-режиме. Cron или /admin/datasets/build
    в manual создаёт строку pending; админ переводит её в approved (запускает
    full build pipeline) или skipped. Прогресс обучения после approve
    отслеживается через datasets.status (source of truth).
    """

    __tablename__ = "training_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    annotations_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gate_issues: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # После approve — ссылка на собранный dataset.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True
    )


class SystemSetting(Base):
    """Гибкий key/value-конфиг рантайма. Сейчас несёт только 'training_mode'
    (JSON `{"localize": "manual|auto|suspended", "tumor": "..."}`). В будущем —
    gate-пороги, частоты cron'а и пр., если выяснится что нужно крутить без
    redeploy'а.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class Model(Base):
    __tablename__ = "models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True
    )
    artifact_path: Mapped[str] = mapped_column(String, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'candidate'"))


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("models.id"), nullable=False
    )
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deployed_by: Mapped[str] = mapped_column(String, nullable=False)
    rollback_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
