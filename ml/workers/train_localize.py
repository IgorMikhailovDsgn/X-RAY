"""Тренировка модели локализации области снимка (Phase 8).

Реальная логика — в `train_common.run_training`. Здесь только Celery-обёртка +
feature-флаг ENABLE_REAL_TRAINING: пока false, таска не тренирует, а откатывает
dataset (освобождает аннотации, гасит demand → GPU-инстанс не залипает на
'ready' навсегда).
"""

import logging
import os

from workers import _internal_api as api
from workers.celery_app import app
from workers.train_common import run_training

logger = logging.getLogger(__name__)

MODEL_TYPE = "localize"


@app.task(name="workers.train_localize.train")
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
