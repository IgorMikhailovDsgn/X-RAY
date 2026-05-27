"""Cron-таска: cleanup зависших dataset_builds. Ходит на server-side endpoint
(вся логика там), нам нужно только периодически дёргать.
"""

from __future__ import annotations

import logging

import httpx

from workers._internal_api import cleanup_hung_builds as _api_cleanup
from workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="workers.maintenance.cleanup_hung_builds")
def cleanup_hung_builds() -> dict[str, object]:
    try:
        result = _api_cleanup()
    except httpx.HTTPError as exc:
        logger.exception("cleanup_hung_builds: internal API failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    cleaned = result.get("cleaned_builds", 0)
    rolled = result.get("rolled_back_datasets", 0)
    if cleaned:
        logger.warning(
            "cleanup_hung_builds: marked %d builds as failed, rolled back %d datasets",
            cleaned, rolled,
        )
    else:
        logger.debug("cleanup_hung_builds: no hung builds")
    return {"ok": True, "result": result}
