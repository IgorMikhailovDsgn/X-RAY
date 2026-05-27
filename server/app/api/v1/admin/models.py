"""Admin endpoints для управления жизненным циклом моделей.

GET    /admin/models               — список моделей (фильтр по типу/статусу).
GET    /admin/models/{id}          — детальная карточка.
POST   /admin/models/{id}/promote  — candidate → prod (archive предыдущей prod-модели,
                                     deactivate её deployments, создать новый
                                     активный deployment).
POST   /admin/models/{id}/archive  — ручной archive без promote (на failed candidate'ы).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select, update

from app.api.v1.deps import AdminUser, SessionDep
from app.core.exceptions import AppError, ConflictError, ValidationAppError
from app.models.mlops import Deployment, Model
from app.schemas.admin import (
    AdminModel,
    AdminModelList,
    ModelStatus,
    ModelType,
    PromoteResponse,
)

router = APIRouter()


def _to_schema(model: Model) -> AdminModel:
    return AdminModel(
        id=model.id,
        model_type=model.model_type,  # type: ignore[arg-type]
        version=model.version,
        trained_at=model.trained_at,
        dataset_id=model.dataset_id,
        artifact_path=model.artifact_path,
        metrics=model.metrics,
        status=model.status,  # type: ignore[arg-type]
    )


@router.get("", response_model=AdminModelList)
async def list_models(
    session: SessionDep,
    _: AdminUser,
    model_type: ModelType | None = Query(default=None),
    status_filter: ModelStatus | None = Query(default=None, alias="status"),
) -> AdminModelList:
    stmt = select(Model).order_by(Model.trained_at.desc())
    if model_type is not None:
        stmt = stmt.where(Model.model_type == model_type)
    if status_filter is not None:
        stmt = stmt.where(Model.status == status_filter)
    rows = (await session.execute(stmt)).scalars().all()
    return AdminModelList(models=[_to_schema(m) for m in rows])


@router.get("/{model_id}", response_model=AdminModel)
async def get_model(
    model_id: uuid.UUID,
    session: SessionDep,
    _: AdminUser,
) -> AdminModel:
    model = await session.get(Model, model_id)
    if model is None:
        raise AppError(
            f"Model {model_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="not_found",
        )
    return _to_schema(model)


@router.post("/{model_id}/promote", response_model=PromoteResponse)
async def promote_model(
    model_id: uuid.UUID,
    session: SessionDep,
    admin: AdminUser,
) -> PromoteResponse:
    target = await session.get(Model, model_id)
    if target is None:
        raise AppError(
            f"Model {model_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="not_found",
        )
    if target.status != "candidate":
        # promote только из candidate — иначе можно случайно переактивировать
        # archived/failed.
        raise ConflictError(
            f"Cannot promote model in status '{target.status}'",
            details={"model_id": str(model_id), "status": target.status},
        )

    # Найти текущую prod-модель этого типа (если есть) — её надо archive'нуть.
    prev_prod_stmt = select(Model).where(
        Model.model_type == target.model_type, Model.status == "prod"
    )
    prev_prod = (await session.execute(prev_prod_stmt)).scalar_one_or_none()

    if prev_prod is not None:
        # Деактивируем все её активные deployments.
        await session.execute(
            update(Deployment)
            .where(Deployment.model_id == prev_prod.id, Deployment.is_active.is_(True))
            .values(is_active=False)
        )
        prev_prod.status = "archived"

    target.status = "prod"
    session.add(
        Deployment(
            model_id=target.id,
            deployed_by=f"manual:{admin.id}",
            is_active=True,
        )
    )
    await session.commit()
    await session.refresh(target)
    if prev_prod is not None:
        await session.refresh(prev_prod)

    return PromoteResponse(
        promoted=_to_schema(target),
        archived=_to_schema(prev_prod) if prev_prod is not None else None,
    )


@router.post("/{model_id}/archive", response_model=AdminModel)
async def archive_model(
    model_id: uuid.UUID,
    session: SessionDep,
    _: AdminUser,
) -> AdminModel:
    model = await session.get(Model, model_id)
    if model is None:
        raise AppError(
            f"Model {model_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="not_found",
        )
    if model.status == "prod":
        # Archive prod через UI ломает /models/deployed — заставляем явно promote
        # другую модель сначала (либо вручную в SQL, если надо «сбросить»).
        raise ValidationAppError(
            "Cannot archive prod model; promote another model first",
            details={"model_id": str(model_id)},
        )
    if model.status == "archived":
        return _to_schema(model)
    model.status = "archived"
    # Гарантируем что не осталось активных deployments у archived модели.
    await session.execute(
        update(Deployment)
        .where(Deployment.model_id == model.id, Deployment.is_active.is_(True))
        .values(is_active=False)
    )
    await session.commit()
    await session.refresh(model)
    return _to_schema(model)
