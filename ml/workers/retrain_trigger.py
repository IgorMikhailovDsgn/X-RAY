"""Cron-таска: спрашивает server'а сформировать датасет для тренировки.

Раньше (Phase 5 до 'e') это был стаб с хардкодом `new_count = 0`. Теперь
дёргает internal-endpoint server'а: реальная логика выбора режима
(auto/manual/suspended), counts и gate-evaluation живёт там — переиспользуем
один пайплайн в обе стороны.

Beat schedule (см. celery_app.py): раз в сутки в 3:00/3:15 UTC.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from workers._internal_api import trigger_build_for_cron
from workers.celery_app import app

logger = logging.getLogger(__name__)

ModelType = Literal["localize", "tumor"]


@app.task(name="workers.retrain_trigger.check_and_trigger")
def check_and_trigger(model_type: ModelType) -> dict[str, object]:
    try:
        result = trigger_build_for_cron(model_type)
    except httpx.HTTPError as exc:
        # Server недоступен или ответил >=400 — не падаем таску, чтобы Celery
        # не ретраил без exponential backoff'а. Следующий cron-tick попробует
        # снова. Логом сигнализируем мониторингу.
        logger.exception(
            "retrain_trigger[%s]: internal API failed: %s", model_type, exc
        )
        return {
            "model_type": model_type,
            "ok": False,
            "error": str(exc),
        }

    status = result.get("status")
    logger.info(
        "retrain_trigger[%s]: status=%s build_id=%s dataset_id=%s candidate_id=%s",
        model_type,
        status,
        result.get("build_id"),
        result.get("dataset_id"),
        result.get("candidate_id"),
    )
    return {"model_type": model_type, "ok": True, "result": result}
