"""One-shot: переносит существующие screenshots/localize объекты на Phase 4 layout.

Старый layout:
    screenshots/<screenshot_id>/monitor_<N>.png
    localize/<image_id>.png

Новый layout:
    screenshots/<device_id>/<YYYY-MM>/<screenshot_id>_m<N>.png
    localize/<device_id>/<YYYY-MM>/<image_id>.png

Идемпотентный: для каждого объекта сравнивает существующий ключ с целевым;
если совпадают — пропускает. Делает copy → update DB → delete old.

Запуск на VPS:
    ssh brainscan-deploy 'docker exec brainscan_server python -m scripts.migrate_s3_layout'
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.db import SessionLocal
from app.models.localize import LocalizeImage
from app.models.screenshot import Screenshot
from app.storage import S3Client
from app.storage.s3 import get_s3_client


def _parse_s3_url(url: str) -> tuple[str, str]:
    # url = "s3://<bucket>/<key>"
    assert url.startswith("s3://"), f"unexpected URL format: {url}"
    rest = url[len("s3://") :]
    bucket, _, key = rest.partition("/")
    return bucket, key


async def _copy_and_delete(
    s3: S3Client, bucket: str, old_key: str, new_key: str
) -> None:
    # boto3 синхронный, гоняем через asyncio.to_thread (как в S3Client.upload_bytes).
    await asyncio.to_thread(
        s3.raw.copy_object,
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": old_key},
        Key=new_key,
    )
    await asyncio.to_thread(s3.raw.delete_object, Bucket=bucket, Key=old_key)


async def _migrate_screenshots(session: AsyncSession, s3: S3Client) -> tuple[int, int]:
    """Returns (migrated_files, skipped_files)."""
    migrated = 0
    skipped = 0
    result = await session.execute(select(Screenshot))
    for screenshot in result.scalars():
        yyyymm = screenshot.captured_at.astimezone(UTC).strftime("%Y-%m")
        new_paths: dict[str, str] = {}
        changed = False
        for monitor_idx_str, old_url in screenshot.screen_paths.items():
            bucket, old_key = _parse_s3_url(old_url)
            new_key = (
                f"{settings.s3_prefix_screenshots}"
                f"{screenshot.device_id}/{yyyymm}/"
                f"{screenshot.id}_m{monitor_idx_str}.png"
            )
            if old_key == new_key:
                new_paths[monitor_idx_str] = old_url
                skipped += 1
                continue
            print(f"  [screen {screenshot.id}] {old_key} -> {new_key}")
            await _copy_and_delete(s3, bucket, old_key, new_key)
            new_paths[monitor_idx_str] = f"s3://{bucket}/{new_key}"
            migrated += 1
            changed = True
        if changed:
            screenshot.screen_paths = new_paths
            # JSONB mutation track: SQLAlchemy не видит in-place изменения dict,
            # переписываем атрибут целиком — этого достаточно.
            flag_modified(screenshot, "screen_paths")
    return migrated, skipped


async def _migrate_localize_images(
    session: AsyncSession, s3: S3Client
) -> tuple[int, int]:
    migrated = 0
    skipped = 0
    # Один query на всё — N+1 здесь приемлем (объектов ~10).
    result = await session.execute(select(LocalizeImage))
    for image in result.scalars():
        screen = await session.get(Screenshot, image.screen_id)
        if screen is None:
            print(
                f"  [localize {image.id}] orphan, нет screenshot {image.screen_id}, skip"
            )
            continue
        yyyymm = screen.captured_at.astimezone(UTC).strftime("%Y-%m")
        bucket, old_key = _parse_s3_url(image.localize_path)
        new_key = (
            f"{settings.s3_prefix_localize}"
            f"{screen.device_id}/{yyyymm}/{image.id}.png"
        )
        if old_key == new_key:
            skipped += 1
            continue
        print(f"  [localize {image.id}] {old_key} -> {new_key}")
        await _copy_and_delete(s3, bucket, old_key, new_key)
        image.localize_path = f"s3://{bucket}/{new_key}"
        migrated += 1
    return migrated, skipped


async def main() -> int:
    s3 = get_s3_client()
    async with SessionLocal() as session:
        print("Phase 4 S3 layout migration starting...")
        s_migrated, s_skipped = await _migrate_screenshots(session, s3)
        print(f"Screenshots:    migrated={s_migrated} skipped={s_skipped}")
        l_migrated, l_skipped = await _migrate_localize_images(session, s3)
        print(f"Localize crops: migrated={l_migrated} skipped={l_skipped}")
        await session.commit()
        print("DB committed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
