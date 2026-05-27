"""Подсчёт статистики свободных аннотаций для конкретной модели.

Источник истины — `localize_annotations.dataset_id IS NULL` (или
`tumor_annotations.dataset_id IS NULL` с фильтром по валидным action'ам).
Используется и `GET /admin/datasets/check` (dry-run), и `POST /datasets/build`
(внутри pipeline'а перед принятием решения).

Сейчас (Phase 5b) все запросы делаются отдельными SELECT'ами для читаемости —
данных мало, нагрузки нет. Если в будущем `compute_stats` станет горячей точкой
profile'инга, объединим в один CTE с FILTER'ами.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.localize import LocalizeAnnotation, LocalizeImage
from app.models.screenshot import Screenshot
from app.models.tumor import TumorAnnotation

ModelType = Literal["localize", "tumor"]
VALID_ACTIONS = ("confirmed", "corrected", "created")


class DeviceBreakdown(BaseModel):
    device_id: str
    total: int
    positive: int


class DatasetStats(BaseModel):
    total_free: int
    positive: int  # bbox NOT NULL
    negative: int  # bbox NULL = "no tumor / null region"
    unique_annotators: int
    max_annotator_pct: float  # 0-100, доля самого активного annotator'а
    by_action: dict[str, int]
    by_device: list[DeviceBreakdown]


async def _annotator_stats(
    session: AsyncSession, model, *extra_filters: Any
) -> tuple[int, float]:
    """Возвращает (unique_annotators, max_annotator_pct).
    Один проход; max_pct = 0.0 если annotator'ов нет.
    """
    base = select(model.annotator_id, func.count().label("c")).where(
        model.dataset_id.is_(None),
        model.action.in_(VALID_ACTIONS),
        *extra_filters,
    ).group_by(model.annotator_id)
    rows = (await session.execute(base)).all()
    if not rows:
        return 0, 0.0
    total = sum(r.c for r in rows)
    max_count = max(r.c for r in rows)
    return len(rows), round(max_count * 100.0 / total, 2)


async def _by_action(
    session: AsyncSession, model, *extra_filters: Any
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(model.action, func.count())
            .where(
                model.dataset_id.is_(None),
                model.action.in_(VALID_ACTIONS),
                *extra_filters,
            )
            .group_by(model.action)
        )
    ).all()
    return {action: count for action, count in rows}


async def compute_localize_stats(session: AsyncSession) -> DatasetStats:
    rows = (
        await session.execute(
            select(
                func.count().filter(LocalizeAnnotation.bbox.isnot(None)).label("pos"),
                func.count().filter(LocalizeAnnotation.bbox.is_(None)).label("neg"),
            ).where(
                LocalizeAnnotation.dataset_id.is_(None),
                LocalizeAnnotation.action.in_(VALID_ACTIONS),
            )
        )
    ).one()
    positive = rows.pos or 0
    negative = rows.neg or 0
    total_free = positive + negative

    unique_ann, max_pct = await _annotator_stats(session, LocalizeAnnotation)
    by_action = await _by_action(session, LocalizeAnnotation)

    # По устройствам — join к screenshots для device_id.
    device_rows = (
        await session.execute(
            select(
                Screenshot.device_id,
                func.count().label("total"),
                func.count().filter(LocalizeAnnotation.bbox.isnot(None)).label("pos"),
            )
            .join(LocalizeAnnotation, LocalizeAnnotation.screen_id == Screenshot.id)
            .where(
                LocalizeAnnotation.dataset_id.is_(None),
                LocalizeAnnotation.action.in_(VALID_ACTIONS),
            )
            .group_by(Screenshot.device_id)
            .order_by(func.count().desc())
        )
    ).all()
    by_device = [
        DeviceBreakdown(device_id=r.device_id, total=r.total, positive=r.pos)
        for r in device_rows
    ]

    return DatasetStats(
        total_free=total_free,
        positive=positive,
        negative=negative,
        unique_annotators=unique_ann,
        max_annotator_pct=max_pct,
        by_action=by_action,
        by_device=by_device,
    )


async def compute_tumor_stats(session: AsyncSession) -> DatasetStats:
    rows = (
        await session.execute(
            select(
                func.count().filter(TumorAnnotation.bbox.isnot(None)).label("pos"),
                func.count().filter(TumorAnnotation.bbox.is_(None)).label("neg"),
            ).where(
                TumorAnnotation.dataset_id.is_(None),
                TumorAnnotation.action.in_(VALID_ACTIONS),
            )
        )
    ).one()
    positive = rows.pos or 0
    negative = rows.neg or 0
    total_free = positive + negative

    unique_ann, max_pct = await _annotator_stats(session, TumorAnnotation)
    by_action = await _by_action(session, TumorAnnotation)

    # Tumor → device_id через двойной join: tumor_annotations → localize_images → screenshots.
    device_rows = (
        await session.execute(
            select(
                Screenshot.device_id,
                func.count().label("total"),
                func.count().filter(TumorAnnotation.bbox.isnot(None)).label("pos"),
            )
            .join(
                LocalizeImage,
                TumorAnnotation.localize_image_id == LocalizeImage.id,
            )
            .join(Screenshot, LocalizeImage.screen_id == Screenshot.id)
            .where(
                TumorAnnotation.dataset_id.is_(None),
                TumorAnnotation.action.in_(VALID_ACTIONS),
            )
            .group_by(Screenshot.device_id)
            .order_by(func.count().desc())
        )
    ).all()
    by_device = [
        DeviceBreakdown(device_id=r.device_id, total=r.total, positive=r.pos)
        for r in device_rows
    ]

    return DatasetStats(
        total_free=total_free,
        positive=positive,
        negative=negative,
        unique_annotators=unique_ann,
        max_annotator_pct=max_pct,
        by_action=by_action,
        by_device=by_device,
    )


async def compute_stats(session: AsyncSession, model_type: ModelType) -> DatasetStats:
    if model_type == "localize":
        return await compute_localize_stats(session)
    return await compute_tumor_stats(session)
