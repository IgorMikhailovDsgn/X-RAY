"""Тренировка модели детекции опухоли на crop'е области интереса (Phase 8).

Симметрично train_localize — реальная логика в `train_common.run_training`.
"""

import logging
import os

from workers import _internal_api as api
from workers.celery_app import app
from workers.train_common import run_training

logger = logging.getLogger(__name__)

MODEL_TYPE = "tumor"


@app.task(name="workers.train_tumor.train")
def train(dataset_id: str) -> dict[str, object]:
    enabled = os.environ.get("ENABLE_REAL_TRAINING", "false").lower() == "true"
    if not enabled:
        logger.info(
            "train_%s: ENABLE_REAL_TRAINING=false, rolling back dataset %s",
            MODEL_TYPE,
            dataset_id,
        )
        if dataset_id:
            api.training_fail(dataset_id, reason="real_training_disabled")
        return {"status": "skipped", "reason": "real_training_disabled"}

    return run_training(MODEL_TYPE, dataset_id)
