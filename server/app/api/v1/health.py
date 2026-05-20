import asyncio
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.v1.deps import SessionDep, StorageDep
from app.config import settings
from app.storage import S3Client

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 2.0


async def _ping_db(session: SessionDep) -> str:
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:  # noqa: BLE001
        return "degraded"


async def _ping_storage(storage: S3Client) -> str:
    try:
        await asyncio.wait_for(
            storage.head_bucket(settings.s3_bucket_screenshots),
            CHECK_TIMEOUT_SECONDS,
        )
        return "ok"
    except Exception:  # noqa: BLE001
        return "degraded"


@router.get("")
async def health(session: SessionDep, storage: StorageDep) -> dict[str, Any]:
    db_status, storage_status = await asyncio.gather(
        _ping_db(session), _ping_storage(storage)
    )
    return {
        "status": "ok",
        "version": settings.app_version,
        "db": db_status,
        "storage": storage_status,
    }
