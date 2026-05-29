"""Cron-таска GPU-автоскейла: дёргает /internal/gpu/reconcile на server'е.

Вся логика (поднять/держать/погасить) — на server-стороне (gpu_orchestrator),
у которого есть DB + openstacksdk + Selectel-креды. Воркер только триггерит по
расписанию (каждые ~2 мин, см. celery_app.beat_schedule).
"""

from __future__ import annotations

import logging

import httpx

from workers._internal_api import gpu_reconcile as _api_reconcile
from workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="workers.gpu_autoscaler.reconcile")
def reconcile() -> dict[str, object]:
    try:
        result = _api_reconcile()
    except httpx.HTTPError as exc:
        logger.exception("gpu_autoscaler: internal API failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    action = result.get("action")
    if action not in ("disabled", "idle_no_instance", "keep_warm", "bump"):
        # Значимые действия (provisioned/deleted/failed) — на уровень INFO/WARNING.
        logger.warning("gpu_autoscaler: %s", result)
    else:
        logger.debug("gpu_autoscaler: %s", result)
    return {"ok": True, "result": result}
