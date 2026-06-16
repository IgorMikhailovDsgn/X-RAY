import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TumorDetection(Base):
    __tablename__ = "tumor_detections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    localize_image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("localize_images.id"), nullable=False
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("models.id"), nullable=False
    )
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


class TumorAnnotation(Base):
    __tablename__ = "tumor_annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    localize_image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("localize_images.id"), nullable=False
    )
    detection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tumor_detections.id"), nullable=True
    )
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
    # См. LocalizeAnnotation.dataset_id — двухфазная reservation, Phase 5b/c.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True
    )
    # Weighted-training сигналы (Phase 10, миграция 0007). См. LocalizeAnnotation.
    correction_type: Mapped[str | None] = mapped_column(String, nullable=True)
    iou_with_detection: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_weight: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("1.0")
    )
