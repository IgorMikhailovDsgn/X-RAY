"""Полная реализация Phase 5c: from annotations to ready-to-train manifest.

`build_and_reserve(session, s3, model_type, stats) -> Dataset` собирает датасет
из всех свободных аннотаций для `model_type`:

1. `_next_version` — следующий integer-suffix к "v{N}" в datasets.version.
2. `_load_samples_*` — загружает annotation + screen + crop_path.
3. `_group_shuffle_split` — anti-leakage split по screen_id (одна съёмка не
   разделяется между train/val/test). Class-balance проверяется после
   разбиения; при сильном перекосе — retry с другим seed.
4. `_build_manifest_dict` — формирует JSON по формату из плана.
5. S3 upload + atomic reservation в одной транзакции:
   `INSERT datasets(building)` → manifest в S3 → `UPDATE annotations SET dataset_id`
   → `UPDATE datasets SET status='ready'`.

Принципиально: всё внутри одной session транзакции, которую коммитит caller
(`run_build`). Если на любом этапе будет exception, caller rollback'нёт всё
включая черновой dataset row и аннотации останутся свободны.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.localize import LocalizeAnnotation, LocalizeImage
from app.models.mlops import Dataset
from app.models.screenshot import Screenshot
from app.models.tumor import TumorAnnotation
from app.services.dataset_stats import VALID_ACTIONS, DatasetStats, ModelType
from app.storage import S3Client

DEFAULT_SEED = 42
SPLIT_RATIO = (0.7, 0.2, 0.1)  # train / val / test
MIN_SPLIT_POSITIVE_FRACTION = 0.05  # ловим явные перекосы при малых выборках


class DatasetBuildError(RuntimeError):
    """Build не получился по структурной причине (нет данных / перекосы)."""


# --------------------------- version helpers ---------------------------


async def _next_version(session: AsyncSession, model_type: str) -> str:
    """Следующий integer-suffix. "v3" -> "v4". Если для типа ещё не было
    датасетов — "v1". Регулярка нестрогая: всё что после первого 'v' и есть
    цифрами трактуется как номер; невалидные форматы (например, ручной
    "experimental") — игнорируются.
    """
    rows = (
        await session.execute(
            select(Dataset.version).where(Dataset.model_type == model_type)
        )
    ).scalars().all()
    max_n = 0
    for v in rows:
        if v.startswith("v"):
            tail = v[1:].split(".", 1)[0]  # на случай "v1.3" в legacy
            if tail.isdigit():
                max_n = max(max_n, int(tail))
    return f"v{max_n + 1}"


# --------------------------- sample loading ---------------------------


async def _load_localize_samples(session: AsyncSession) -> list[dict[str, Any]]:
    """Возвращает список samples: каждый sample самодостаточен для манифеста."""
    rows = (
        await session.execute(
            select(
                LocalizeAnnotation.id,
                LocalizeAnnotation.screen_id,
                LocalizeAnnotation.bbox,
                LocalizeAnnotation.annotator_id,
                LocalizeAnnotation.monitor_index,
                Screenshot.screen_paths,
            )
            .join(Screenshot, LocalizeAnnotation.screen_id == Screenshot.id)
            .where(
                LocalizeAnnotation.dataset_id.is_(None),
                LocalizeAnnotation.action.in_(VALID_ACTIONS),
            )
            .order_by(LocalizeAnnotation.annotated_at)
        )
    ).all()
    samples: list[dict[str, Any]] = []
    for r in rows:
        monitor_key = str(r.monitor_index)
        crop_path = (r.screen_paths or {}).get(monitor_key)
        if not crop_path:
            # Защита от inconsistent state: annotation указывает на монитор,
            # которого нет в screen_paths. Пропускаем (не падаем — это не
            # фатально, сам annotation остаётся в DB и попадёт в следующий dataset
            # если/когда screen_paths починят).
            continue
        samples.append(
            {
                "annotation_id": str(r.id),
                "screen_id": str(r.screen_id),
                "crop_path": crop_path,
                "label": "localize" if r.bbox else "negative",
                "bbox": r.bbox,
                "annotator_id": r.annotator_id,
            }
        )
    return samples


async def _load_tumor_samples(session: AsyncSession) -> list[dict[str, Any]]:
    """tumor → join к localize_images.localize_path. group для split'а —
    screen_id родительского screenshot'а (через localize_images.screen_id).
    """
    rows = (
        await session.execute(
            select(
                TumorAnnotation.id,
                TumorAnnotation.bbox,
                TumorAnnotation.annotator_id,
                LocalizeImage.screen_id,
                LocalizeImage.localize_path,
            )
            .join(
                LocalizeImage,
                TumorAnnotation.localize_image_id == LocalizeImage.id,
            )
            .where(
                TumorAnnotation.dataset_id.is_(None),
                TumorAnnotation.action.in_(VALID_ACTIONS),
            )
            .order_by(TumorAnnotation.annotated_at)
        )
    ).all()
    samples: list[dict[str, Any]] = []
    for r in rows:
        samples.append(
            {
                "annotation_id": str(r.id),
                "screen_id": str(r.screen_id),
                "crop_path": r.localize_path,
                "label": "tumor" if r.bbox else "negative",
                "bbox": r.bbox,
                "annotator_id": r.annotator_id,
            }
        )
    return samples


async def _load_samples(
    session: AsyncSession, model_type: ModelType
) -> list[dict[str, Any]]:
    if model_type == "localize":
        return await _load_localize_samples(session)
    return await _load_tumor_samples(session)


# --------------------------- stratified split ---------------------------


def _group_shuffle_split(
    samples: list[dict[str, Any]],
    *,
    ratio: tuple[float, float, float] = SPLIT_RATIO,
    seed: int = DEFAULT_SEED,
) -> tuple[list[int], list[int], list[int]]:
    """Anti-leakage split: все samples с одинаковым screen_id попадают в один
    split. Возвращает три списка индексов в `samples`.

    Аллокация по группам, не по items — поэтому фактические доли могут слегка
    плыть от заданных при маленьких выборках. Проверка class-balance делается
    в `build_and_reserve` снаружи.
    """
    rng = random.Random(seed)
    # Группируем по screen_id.
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(samples):
        groups.setdefault(s["screen_id"], []).append(i)
    keys = list(groups.keys())
    rng.shuffle(keys)
    n = len(keys)
    train_n = max(1, int(n * ratio[0]))
    val_n = max(0, int(n * ratio[1]))
    train_keys = set(keys[:train_n])
    val_keys = set(keys[train_n : train_n + val_n])
    # test = всё остальное (включая edge-case где val_n + train_n покрыло всех)
    train_idx: list[int] = []
    val_idx: list[int] = []
    test_idx: list[int] = []
    for g, idxs in groups.items():
        bucket = (
            train_idx if g in train_keys else val_idx if g in val_keys else test_idx
        )
        bucket.extend(idxs)
    return train_idx, val_idx, test_idx


def _split_with_balance_check(
    samples: list[dict[str, Any]], seed: int = DEFAULT_SEED, max_retries: int = 3
) -> tuple[list[int], list[int], list[int], int]:
    """Возвращает (train, val, test, used_seed). Делает до `max_retries`
    попыток с разными seed'ами, чтобы получить хотя бы 1 positive в каждом
    непустом split'е (защита от degenerate split'ов на крошечных выборках).
    """
    current_seed = seed
    for _ in range(max_retries):
        tr, va, te = _group_shuffle_split(samples, seed=current_seed)

        def has_positive(idxs: list[int]) -> bool:
            return any(samples[i]["bbox"] is not None for i in idxs)

        ok_train = (not tr) or has_positive(tr)
        ok_val = (not va) or has_positive(va)
        ok_test = (not te) or has_positive(te)
        if ok_train and ok_val and ok_test:
            return tr, va, te, current_seed
        current_seed += 1
    # Если за max_retries не нашли — возвращаем последний результат как есть;
    # gate перед нами уже проверил суммарный баланс, недостаток в split'е по
    # 3-5 семплам — не повод падать.
    return tr, va, te, current_seed


# --------------------------- manifest ---------------------------


def _manifest_sample(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "annotation_id": s["annotation_id"],
        "screen_id": s["screen_id"],
        "crop_path": s["crop_path"],
        "label": s["label"],
        "bbox": s["bbox"],
        "annotator_id": s["annotator_id"],
    }


def _compute_manifest_checksum(samples: list[dict[str, Any]]) -> str:
    # Стабильный отпечаток выборки: SHA-256 от отсортированного списка
    # annotation_id. Если два build'а дали идентичный набор аннотаций —
    # checksum совпадёт (полезно для "уже учили на этом, не повторяться").
    sorted_ids = sorted(s["annotation_id"] for s in samples)
    h = hashlib.sha256("\n".join(sorted_ids).encode("utf-8"))
    return f"sha256:{h.hexdigest()}"


def _build_manifest_dict(
    *,
    dataset_id: uuid.UUID,
    version: str,
    model_type: str,
    stats: DatasetStats,
    samples: list[dict[str, Any]],
    train_idx: list[int],
    val_idx: list[int],
    test_idx: list[int],
    seed: int,
) -> dict[str, Any]:
    return {
        "dataset_id": str(dataset_id),
        "version": version,
        "model_type": model_type,
        "created_at": datetime.now(UTC).isoformat(),
        "stats": stats.model_dump(),
        "split_ratio": {
            "train": SPLIT_RATIO[0],
            "val": SPLIT_RATIO[1],
            "test": SPLIT_RATIO[2],
        },
        "seed": seed,
        "splits": {
            "train": [_manifest_sample(samples[i]) for i in train_idx],
            "val": [_manifest_sample(samples[i]) for i in val_idx],
            "test": [_manifest_sample(samples[i]) for i in test_idx],
        },
        "checksum": _compute_manifest_checksum(samples),
    }


def _manifest_s3_key(model_type: str, version: str) -> str:
    # Phase 9 layout: `<s3_prefix_datasets><type>/<version>/manifest.json`.
    # datasets/ — отдельный top-level префикс рядом с models/, а не внутри.
    return (
        f"{settings.s3_prefix_datasets}{model_type}/{version}/manifest.json"
    )


# --------------------------- main entry ---------------------------


async def build_and_reserve(
    session: AsyncSession,
    s3: S3Client,
    model_type: ModelType,
    stats: DatasetStats,
) -> Dataset:
    """Создаёт dataset row, формирует split + manifest, загружает в S3,
    атомарно резервирует аннотации. Возвращает готовый Dataset (status='ready').

    НЕ коммитит — caller (`run_build`) делает COMMIT после, чтобы advisory lock
    и audit-row dataset_builds попали в одну транзакцию с reservation'ом.
    """
    samples = await _load_samples(session, model_type)
    if not samples:
        raise DatasetBuildError("No free annotations to build dataset")

    version = await _next_version(session, model_type)
    train_idx, val_idx, test_idx, used_seed = _split_with_balance_check(samples)

    # INSERT датасета сразу с финальными size_*, чтобы chk_datasets_sizes
    # (size_total = train + val + test) не споткнулся на промежуточных нулях.
    manifest_key = _manifest_s3_key(model_type, version)
    bucket = settings.s3_bucket_models
    dataset = Dataset(
        model_type=model_type,
        version=version,
        size_total=len(samples),
        size_train=len(train_idx),
        size_val=len(val_idx),
        size_test=len(test_idx),
        manifest_path=f"s3://{bucket}/{manifest_key}",
        status="building",
        stats=stats.model_dump(),
    )
    session.add(dataset)
    await session.flush()  # получаем dataset.id

    manifest = _build_manifest_dict(
        dataset_id=dataset.id,
        version=version,
        model_type=model_type,
        stats=stats,
        samples=samples,
        train_idx=train_idx,
        val_idx=val_idx,
        test_idx=test_idx,
        seed=used_seed,
    )

    await s3.upload_bytes(
        bucket=bucket,
        key=manifest_key,
        content=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json",
    )

    # Atomic reservation: помечаем все вошедшие аннотации dataset_id.
    annotation_ids = [uuid.UUID(s["annotation_id"]) for s in samples]
    annotation_model = (
        LocalizeAnnotation if model_type == "localize" else TumorAnnotation
    )
    await session.execute(
        update(annotation_model)
        .where(annotation_model.id.in_(annotation_ids))
        .values(dataset_id=dataset.id)
    )

    dataset.status = "ready"
    await session.flush()
    return dataset
