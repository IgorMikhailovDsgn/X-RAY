"""Aggregator-router для всех /api/v1/admin/* endpoint'ов.

Подключается в `main.py` одной строкой; внутри собирает sub-router'ы (models,
datasets, training — добавляются по мере реализации Phase 5/6).
"""

from fastapi import APIRouter

from app.api.v1.admin import models

router = APIRouter()
router.include_router(models.router, prefix="/models", tags=["admin:models"])
