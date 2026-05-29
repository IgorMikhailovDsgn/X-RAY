"""Серверная логика lifecycle обучения (Phase 8).

GPU-worker дёргает три точки вокруг реальной тренировки:

- `start_training`  — берёт dataset 'ready' → 'training', отдаёт manifest_path.
- `complete_training` — INSERT models(candidate) + dataset → 'completed'.
- `fail_training`   — откат: dataset → 'failed', аннотации dataset_id=NULL.

Все три идемпотентны: повторный вызов после сетевого сбоя не ломает состояние
(start на 'training' — no-op; complete на 'completed' — вернёт ту же модель;
fail на 'failed' — повторный откат пустой).

Сам build (dataset_builds) на training-failure НЕ трогаем: build своё дело
сделал (dataset собран), а провал обучения — отдельная стадия. Освобождённые
аннотации подберёт следующий build, создав новый dataset с новой версией.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError
from app.models.localize import LocalizeAnnotation
from app.models.mlops import Dataset, Model
from app.models.tumor import TumorAnnotation
from app.schemas.training import (
    TrainingCompleteResponse,
    TrainingFailResponse,
    TrainingStartResponse,
)


class DatasetNotFoundError(AppError):
    status_code = 404
    error_code = "not_found"


class DatasetStateError(ConflictError):
    error_code = "dataset_state"


def _annotation_model(model_type: str) -> type[LocalizeAnnotation] | type[TumorAnnotation]:
    return LocalizeAnnotation if model_type == "localize" else TumorAnnotation


async def _get_dataset(session: AsyncSession, dataset_id: uuid.UUID) -> Dataset:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise DatasetNotFoundError(f"Dataset {dataset_id} not found")
    return dataset


async def start_training(
    session: AsyncSession, dataset_id: uuid.UUID
) -> TrainingStartResponse:
    """ready → training. Идемпотентно при повторе на 'training'."""
    dataset = await _get_dataset(session, dataset_id)
    if dataset.status == "ready":
        dataset.status = "training"
        await session.commit()
    elif dataset.status == "training":
        pass  # повторный старт того же таска — ничего не делаем
    else:
        raise DatasetStateError(
            f"Dataset is '{dataset.status}', expected 'ready' to start training",
            details={"dataset_id": str(dataset_id), "status": dataset.status},
        )
    return TrainingStartResponse(
        dataset_id=dataset.id,
        model_type=dataset.model_type,  # type: ignore[arg-type]
        version=dataset.version,
        manifest_path=dataset.manifest_path,
    )


async def complete_training(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    artifact_path: str,
    metrics: dict[str, object],
    mlflow_run_id: str | None,
) -> TrainingCompleteResponse:
    """Регистрирует обученную модель (candidate) и закрывает dataset.

    Идемпотентно: если dataset уже 'completed', возвращает ранее созданную
    модель этой версии вместо дубля.
    """
    dataset = await _get_dataset(session, dataset_id)

    if dataset.status == "completed":
        existing = (
            await session.execute(
                select(Model).where(
                    Model.dataset_id == dataset.id, Model.status != "failed"
                )
            )
        ).scalars().first()
        if existing is not None:
            return TrainingCompleteResponse(
                model_id=existing.id, version=existing.version, status="candidate"
            )

    if dataset.status not in ("training", "completed"):
        raise DatasetStateError(
            f"Dataset is '{dataset.status}', expected 'training' to complete",
            details={"dataset_id": str(dataset_id), "status": dataset.status},
        )

    stored_metrics = dict(metrics)
    if mlflow_run_id:
        stored_metrics["mlflow_run_id"] = mlflow_run_id

    model = Model(
        model_type=dataset.model_type,
        version=dataset.version,
        dataset_id=dataset.id,
        artifact_path=artifact_path,
        metrics=stored_metrics,
        status="candidate",
    )
    session.add(model)
    dataset.status = "completed"
    await session.commit()
    await session.refresh(model)
    return TrainingCompleteResponse(
        model_id=model.id, version=model.version, status="candidate"
    )


async def fail_training(
    session: AsyncSession, dataset_id: uuid.UUID, reason: str
) -> TrainingFailResponse:
    """Откат при провале обучения: dataset → 'failed', аннотации в свободный пул.

    Идемпотентно: повтор на уже 'failed' dataset'е вернёт 0 откатанных (аннотации
    уже освобождены).
    """
    dataset = await _get_dataset(session, dataset_id)
    if dataset.status == "failed":
        return TrainingFailResponse(dataset_id=dataset.id, rolled_back_annotations=0)

    ann_model = _annotation_model(dataset.model_type)
    reserved = (
        await session.execute(
            select(func.count())
            .select_from(ann_model)
            .where(ann_model.dataset_id == dataset.id)
        )
    ).scalar_one()
    await session.execute(
        update(ann_model)
        .where(ann_model.dataset_id == dataset.id)
        .values(dataset_id=None)
    )
    dataset.status = "failed"
    dataset.failed_reason = reason
    await session.commit()
    return TrainingFailResponse(
        dataset_id=dataset.id,
        rolled_back_annotations=reserved,
    )
