"""S3 + БД helper для создания `localize_images` row из crop'а.

Используется и `/detect` (детекция нашла регион → server режет crop сам,
аннотации ещё нет), и batch-`/detect/annotations` (юзер прислал новый bbox →
тоже режем crop на сервере, чтобы не дублировать crop-логику в клиенте).

Координатная конвенция: bbox в screen-space (физ. пиксели исходного скрина,
top-left origin) — та же, что в `localize_detections.bbox`/`localize_annotations.bbox`.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.localize import LocalizeImage
from app.models.screenshot import Screenshot
from app.services import inference
from app.storage import S3Client


async def create_localize_image(
    session: AsyncSession,
    storage: S3Client,
    *,
    screen: Screenshot,
    monitor_index: int,
    bbox: dict[str, Any],
    image_bytes: bytes,
    detection_id: uuid.UUID | None,
    annotation_id: uuid.UUID | None,
) -> LocalizeImage:
    """Crop из `image_bytes` по `bbox`, заливка в S3, INSERT `localize_images`.

    Возвращает объект уже добавленный в сессию через session.add() — caller
    решает когда `await session.flush()`/`commit()`.

    Хотя бы один из detection_id/annotation_id обязателен — это требование
    `chk_loc_img_source` в схеме. Caller должен это обеспечить.
    """
    if detection_id is None and annotation_id is None:
        raise ValueError(
            "create_localize_image requires detection_id or annotation_id"
        )

    crop_bytes = inference.crop_png(image_bytes, bbox)
    ddmmyy = screen.captured_at.astimezone(UTC).strftime("%d.%m.%y")
    image_id = uuid.uuid4()
    key = (
        f"{settings.s3_prefix_localize}"
        f"{screen.device_id}/{ddmmyy}/{image_id}.png"
    )
    localize_path = await storage.upload_bytes(
        bucket=settings.s3_bucket_localize,
        key=key,
        content=crop_bytes,
        content_type="image/png",
    )

    record = LocalizeImage(
        id=image_id,
        screen_id=screen.id,
        detection_id=detection_id,
        annotation_id=annotation_id,
        monitor_index=monitor_index,
        bbox=bbox,
        localize_path=localize_path,
    )
    session.add(record)
    return record
