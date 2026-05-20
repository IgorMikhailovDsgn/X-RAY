"""Тренировка модели детекции опухоли на crop'е области интереса.

В MVP: stub. Симметрично train_localize.train — см. там подробности.
"""

import logging
import os
from uuid import uuid4

from workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="workers.train_tumor.train")
def train(dataset_id: str | None = None) -> dict[str, str]:
    enabled = os.environ.get("ENABLE_REAL_TRAINING", "false").lower() == "true"
    if not enabled:
        logger.info("train_tumor: ENABLE_REAL_TRAINING=false, skipping real training")
        return {
            "status": "skipped",
            "reason": "real_training_disabled",
            "stub_model_id": str(uuid4()),
        }

    raise NotImplementedError("real training to be implemented in Phase E")
