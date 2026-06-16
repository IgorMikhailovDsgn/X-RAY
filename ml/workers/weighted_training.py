"""Phase 10 stage C: weighted training через WeightedRandomSampler.

Подход (см. план):
- Сервер уже пишет `training_weight` в каждую `*_annotations` строку и
  пробрасывает в manifest.
- В `_prepare_yolo_dataset` мы дополнительно пишем `weights.json`
  (annotation_id → training_weight) рядом с `data.yaml`.
- `WeightedDetectionTrainer` подменяет train-DataLoader на DataLoader
  с `torch.utils.data.WeightedRandomSampler`. Каждый сэмпл «видится»
  моделью пропорционально его весу:

  P(seen sample i in epoch) ≈ w_i / Σ w_j

  Это эквивалент per-sample loss weighting в матожидании градиента,
  но не требует переопределения `v8DetectionLoss` (хрупкая часть
  ultralytics — мы её обходим).
- Eval/test (`mode != 'train'`) — без весов, стандартный DataLoader.

Если в weights_map отсутствуют записи → сэмпл получает вес 1.0 (legacy
данные, в т.ч. исторические аннотации до миграции 0007).

Все ultralytics-импорты ленивы: на CPU-worker'е/тестах модуль грузится
дёшево, без torch.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_weights_map(workdir: Path) -> dict[str, float]:
    """Читает `weights.json` рядом с `data.yaml`. Если файла нет — пустой dict
    (трактуется как «все веса = 1.0»).
    """
    path = workdir / "weights.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        logger.warning("weighted: cannot read %s: %s", path, exc)
        return {}
    return {str(k): float(v) for k, v in raw.items()}


def write_weights_map(workdir: Path, weights: dict[str, float]) -> None:
    """Записывает weights.json. Пустой dict не пишется — трейнеру это
    эквивалентно baseline-режиму (все веса 1.0).
    """
    if not weights:
        return
    path = workdir / "weights.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(weights, f)


def build_sampler_weights(
    im_files: list[str], weights_map: dict[str, float]
) -> list[float]:
    """Для каждого image-файла из YOLO-датасета берёт вес из weights_map по
    basename (annotation_id). Отсутствующий ключ → 1.0. Используется
    `WeightedDetectionTrainer` для создания `WeightedRandomSampler`.
    """
    out: list[float] = []
    for path in im_files:
        stem = Path(path).stem
        out.append(float(weights_map.get(stem, 1.0)))
    return out


def make_weighted_trainer_class(weights_map: dict[str, float]) -> Any:
    """Factory: возвращает класс DetectionTrainer'а, замыкающий weights_map.

    Используется так:
    ```
    Trainer = make_weighted_trainer_class(weights_map)
    model.train(..., trainer=Trainer)
    ```

    Логика: `get_dataloader('train', ...)` подменяет дефолтный DataLoader на
    DataLoader с WeightedRandomSampler. Eval/val/test остаются без изменений.
    """
    from torch.utils.data import DataLoader, WeightedRandomSampler
    from ultralytics.models.yolo.detect import DetectionTrainer

    if not weights_map:
        # Нет ни одной строки в weights.json — отдаём baseline-trainer.
        # Поведение идентично `model.train()` без trainer-override'а.
        return DetectionTrainer

    class _WeightedDetectionTrainer(DetectionTrainer):
        _wt_weights_map = weights_map

        def get_dataloader(self, dataset_path, batch_size=16, rank=0, mode="train"):
            loader = super().get_dataloader(
                dataset_path, batch_size=batch_size, rank=rank, mode=mode
            )
            if mode != "train":
                return loader
            dataset = loader.dataset
            sampler_weights = build_sampler_weights(
                dataset.im_files, self._wt_weights_map
            )
            non_default = sum(1 for w in sampler_weights if w != 1.0)
            if non_default == 0:
                # weights_map не пересёкся ни с одним файлом → baseline.
                logger.info(
                    "weighted: no overlap with dataset files, falling back to default sampler"
                )
                return loader
            sampler = WeightedRandomSampler(
                weights=sampler_weights,
                num_samples=len(sampler_weights),
                replacement=True,
            )
            logger.info(
                "weighted: WeightedRandomSampler attached "
                "(n=%d, weighted_samples=%d, sum_weights=%.2f)",
                len(sampler_weights),
                non_default,
                sum(sampler_weights),
            )
            # Воспроизводим параметры родительского loader'а, кроме shuffle:
            # с sampler'ом shuffle нельзя.
            return DataLoader(
                dataset,
                batch_size=loader.batch_size,
                sampler=sampler,
                num_workers=loader.num_workers,
                collate_fn=loader.collate_fn,
                pin_memory=loader.pin_memory,
                drop_last=False,
                persistent_workers=getattr(loader, "persistent_workers", False),
            )

    return _WeightedDetectionTrainer


def correction_type_breakdown(manifest: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Группирует annotation_id по correction_type в split'ах val/test.
    Возвращает {split: {correction_type: [annotation_ids...]}}.

    Используется для post-hoc разрезов recall в MLflow.
    """
    out: dict[str, dict[str, list[str]]] = {}
    for split in ("val", "test"):
        samples = manifest.get("splits", {}).get(split, [])
        per_type: dict[str, list[str]] = {}
        for s in samples:
            key = s.get("correction_type") or "confirmed"
            per_type.setdefault(key, []).append(str(s.get("annotation_id")))
        out[split] = per_type
    return out


def weight_stats(weights_map: dict[str, float]) -> dict[str, float]:
    """Базовая сводка по весам в датасете (мин/макс/среднее/доля weighted)."""
    if not weights_map:
        return {"count": 0.0, "mean": 0.0, "max": 0.0, "min": 0.0, "high_pct": 0.0}
    values = list(weights_map.values())
    n = float(len(values))
    high = sum(1 for v in values if v > 1.5)
    return {
        "count": n,
        "mean": sum(values) / n,
        "max": max(values),
        "min": min(values),
        "high_pct": high / n,
    }
