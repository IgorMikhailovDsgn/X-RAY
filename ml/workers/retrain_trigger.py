"""Триггер дообучения. Раз в сутки проверяет накопление новых аннотаций
с момента последнего датасета. При превышении порога RETRAIN_THRESHOLD
запускает соответствующий train-таск.

В MVP реальная тренировка отключена (см. train_localize / train_tumor).
"""

import logging
import os
from typing import Literal

from workers.celery_app import app

logger = logging.getLogger(__name__)

ModelType = Literal["localize", "tumor"]


@app.task(name="workers.retrain_trigger.check_and_trigger")
def check_and_trigger(model_type: ModelType) -> dict[str, object]:
    threshold = int(os.environ.get("RETRAIN_THRESHOLD", "1000"))

    # TODO Phase B/E: реальный SQL
    # Сейчас stub — счётчик новых аннотаций берётся из БД:
    #   SELECT COUNT(*)
    #   FROM {model_type}_annotations
    #   WHERE annotated_at > (SELECT COALESCE(MAX(created_at), '1970-01-01')
    #                         FROM datasets WHERE model_type = :model_type);
    new_count = 0

    if new_count < threshold:
        logger.info(
            "retrain_trigger[%s]: %d/%d new annotations, threshold not reached",
            model_type, new_count, threshold,
        )
        return {"model_type": model_type, "triggered": False, "new_annotations": new_count}

    task_name = f"workers.train_{model_type}.train"
    app.send_task(task_name)
    logger.info("retrain_trigger[%s]: triggered %s", model_type, task_name)
    return {"model_type": model_type, "triggered": True, "new_annotations": new_count}
