"""Тренировка модели локализации области снимка.

В MVP: stub. Логирует запуск в MLflow, создаёт пустой artifact в S3 и
регистрирует row в `models` со status='candidate'. Реальная тренировка
появится в V2 (Phase E или отдельный план), когда накопится первый
размеченный датасет.
"""

import logging
import os
from uuid import uuid4

from workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="workers.train_localize.train")
def train(dataset_id: str | None = None) -> dict[str, str]:
    enabled = os.environ.get("ENABLE_REAL_TRAINING", "false").lower() == "true"
    if not enabled:
        logger.info("train_localize: ENABLE_REAL_TRAINING=false, skipping real training")
        return {
            "status": "skipped",
            "reason": "real_training_disabled",
            "stub_model_id": str(uuid4()),
        }

    # TODO Phase E: реальная тренировка
    # 1. Загрузить манифест датасета из S3 (или пересобрать из БД)
    # 2. Запустить mlflow.start_run(), залогировать гиперпараметры
    # 3. Натренировать YOLOv8 / другую модель
    # 4. Залить веса в S3, зарегистрировать в models со status='candidate'
    # 5. Опционально: автопромоут в prod если recall не упал
    raise NotImplementedError("real training to be implemented in Phase E")
