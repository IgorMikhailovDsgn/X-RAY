"""Тонкий клиент к /api/v1/internal/* эндпоинтам server'а.

Воркер живёт в отдельном Docker-image без `app/` — общую pipeline-логику
переиспользуем через HTTP. Аутентификация — `X-Internal-Token` shared secret
из env. Без этих переменных модуль падает на старте (fail-fast).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_INTERNAL_URL_ENV = "INTERNAL_API_URL"  # e.g. http://server:8000
_INTERNAL_TOKEN_ENV = "INTERNAL_API_TOKEN"  # shared secret


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"{key} is required for cron-tasks. Add to deploy/.env, "
            "восстаните контейнер worker'а."
        )
    return value


def _client() -> httpx.Client:
    base_url = _require_env(_INTERNAL_URL_ENV).rstrip("/")
    token = _require_env(_INTERNAL_TOKEN_ENV)
    return httpx.Client(
        base_url=base_url,
        headers={"X-Internal-Token": token},
        # Достаточный timeout под worst-case auto-build (manifest + S3 upload).
        # Если cron упрётся в этот лимит — лучше увидеть таймаут и поднять
        # alert, чем висеть бесконечно.
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0),
    )


def trigger_build_for_cron(model_type: str) -> dict[str, Any]:
    with _client() as c:
        r = c.post(
            "/api/v1/internal/datasets/build/cron",
            json={"model_type": model_type},
        )
        r.raise_for_status()
        return r.json()


def cleanup_hung_builds() -> dict[str, Any]:
    with _client() as c:
        r = c.post("/api/v1/internal/maintenance/cleanup-hung-builds")
        r.raise_for_status()
        return r.json()


def gpu_reconcile() -> dict[str, Any]:
    with _client() as c:
        r = c.post("/api/v1/internal/gpu/reconcile")
        r.raise_for_status()
        return r.json()
