"""Aggregator-router для всех /api/v1/admin/* endpoint'ов.

Подключается в `main.py` одной строкой; внутри собирает sub-router'ы (models,
datasets, training — добавляются по мере реализации Phase 5/6).
"""

from fastapi import APIRouter

from app.api.v1.admin import datasets, gpu, models, training

router = APIRouter()
router.include_router(models.router, prefix="/models", tags=["admin:models"])
router.include_router(datasets.router, prefix="/datasets", tags=["admin:datasets"])
router.include_router(training.router, prefix="/training", tags=["admin:training"])
router.include_router(gpu.router, prefix="/gpu", tags=["admin:gpu"])
