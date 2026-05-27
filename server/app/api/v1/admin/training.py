"""Admin endpoints под training-control: режим (auto/manual/suspended) для
каждой модели. Phase 5d добавит сюда же /candidates/* (approve/skip/list).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import AdminUser, SessionDep
from app.schemas.admin import TrainingModeResponse, TrainingModeUpdate
from app.services.system_settings import get_training_mode, update_training_mode

router = APIRouter()


@router.get("/mode", response_model=TrainingModeResponse)
async def get_mode(session: SessionDep, _: AdminUser) -> TrainingModeResponse:
    mode = await get_training_mode(session)
    return TrainingModeResponse(localize=mode["localize"], tumor=mode["tumor"])


@router.put("/mode", response_model=TrainingModeResponse)
async def put_mode(
    payload: TrainingModeUpdate,
    session: SessionDep,
    admin: AdminUser,
) -> TrainingModeResponse:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    merged = await update_training_mode(session, updates, updated_by=admin.id)
    await session.commit()
    return TrainingModeResponse(localize=merged["localize"], tumor=merged["tumor"])
