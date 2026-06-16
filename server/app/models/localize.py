import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LocalizeDetection(Base):
    __tablename__ = "localize_detections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    screen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screenshots.id"), nullable=False
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("models.id"), nullable=False
    )
    monitor_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # none_as_null: Python None → SQL NULL (а не JSONB-скаляр 'null'). Без этого
    # `bbox IS NULL` в gate/stats не видит негативы → они считаются positive.
    bbox: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # 0..1; nullable — на исторических детекциях (до 0007) значения нет.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta_json_path: Mapped[str | None] = mapped_column(String, nullable=True)
    inferred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LocalizeAnnotation(Base):
    __tablename__ = "localize_annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    screen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screenshots.id"), nullable=False
    )
    detection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("localize_detections.id"), nullable=True
    )
    monitor_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # none_as_null: Python None → SQL NULL (а не JSONB-скаляр 'null'). Без этого
    # `bbox IS NULL` в gate/stats не видит негативы → они считаются positive.
    bbox: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    annotator_id: Mapped[str] = mapped_column(String, nullable=False)
    annotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    meta_json_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # NULL = свободна для следующего dataset'а; value = зарезервирована за этим
    # dataset'ом (Phase 5b/c). При failed training возвращается в NULL.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True
    )
    # Weighted-training сигналы (Phase 10, миграция 0007).
    # NULL для confirmed/cold-start; для corrected — категория ошибки модели.
    correction_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # IoU между detection.bbox и annotation.bbox; полезно для калибровки порогов.
    iou_with_detection: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Множитель loss-функции в train-loop. >0, дефолт 1.0; денормализованно
    # хранится прямо в строке аннотации — потребитель (dataset_builder)
    # пробрасывает в манифест как есть.
    training_weight: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("1.0")
    )


class LocalizeImage(Base):
    __tablename__ = "localize_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    screen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screenshots.id"), nullable=False
    )
    detection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("localize_detections.id"), nullable=True
    )
    annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("localize_annotations.id"), nullable=True
    )
    monitor_index: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    localize_path: Mapped[str] = mapped_column(String, nullable=False)
    meta_json_path: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
