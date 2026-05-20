import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Screenshot(Base):
    __tablename__ = "screenshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    monitor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    screen_paths: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
