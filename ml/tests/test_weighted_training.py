"""Unit-тесты для `workers.weighted_training` без зависимости от torch/ultralytics.

Цель — проверить чистую логику чтения/записи `weights.json`, построения
`sampler_weights` по списку файлов, breakdown'а по correction_type и сводки.
Тесты для `make_weighted_trainer_class` (требующего ultralytics) запускаются
на GPU-боксе как smoke; здесь только косвенно проверяем безопасный no-op
случай.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workers.weighted_training import (
    build_sampler_weights,
    correction_type_breakdown,
    load_weights_map,
    weight_stats,
    write_weights_map,
)

# ----- read / write weights.json -----


def test_load_weights_map_missing_returns_empty(tmp_path: Path):
    assert load_weights_map(tmp_path) == {}


def test_write_then_load_roundtrip(tmp_path: Path):
    src = {"ann-1": 5.0, "ann-2": 1.5, "ann-3": 1.0}
    write_weights_map(tmp_path, src)
    assert load_weights_map(tmp_path) == src


def test_write_empty_skips_file(tmp_path: Path):
    write_weights_map(tmp_path, {})
    assert not (tmp_path / "weights.json").exists()
    assert load_weights_map(tmp_path) == {}


def test_load_weights_map_invalid_json_returns_empty(tmp_path: Path):
    (tmp_path / "weights.json").write_text("{not json}")
    assert load_weights_map(tmp_path) == {}


# ----- build_sampler_weights -----


def test_build_sampler_weights_returns_1_for_missing_keys():
    out = build_sampler_weights(
        ["images/train/ann-1.png", "images/train/ann-2.png"],
        weights_map={},
    )
    assert out == [1.0, 1.0]


def test_build_sampler_weights_uses_basename_lookup():
    out = build_sampler_weights(
        [
            "/workdir/images/train/ann-1.png",
            "/workdir/images/train/ann-2.png",
            "/workdir/images/val/ann-3.png",
        ],
        weights_map={"ann-1": 5.0, "ann-3": 2.5},
    )
    assert out == [5.0, 1.0, 2.5]


# ----- correction_type_breakdown -----


def test_correction_type_breakdown_groups_by_type_and_split():
    manifest = {
        "splits": {
            "train": [
                {"annotation_id": "tr-1", "correction_type": "false_negative"},
            ],
            "val": [
                {"annotation_id": "v-1", "correction_type": "false_negative"},
                {"annotation_id": "v-2", "correction_type": None},
                {"annotation_id": "v-3", "correction_type": "wrong_location"},
            ],
            "test": [
                {"annotation_id": "te-1", "correction_type": "false_positive"},
            ],
        }
    }
    out = correction_type_breakdown(manifest)
    # Train не возвращается — только val/test (eval-режимы).
    assert set(out.keys()) == {"val", "test"}
    # val: confirmed (None), false_negative, wrong_location.
    assert set(out["val"]["confirmed"]) == {"v-2"}
    assert set(out["val"]["false_negative"]) == {"v-1"}
    assert set(out["val"]["wrong_location"]) == {"v-3"}
    assert set(out["test"]["false_positive"]) == {"te-1"}


def test_correction_type_breakdown_empty_manifest():
    assert correction_type_breakdown({}) == {"val": {}, "test": {}}


# ----- weight_stats -----


def test_weight_stats_basic():
    out = weight_stats({"a": 1.0, "b": 2.5, "c": 5.0, "d": 1.0})
    assert out["count"] == 4.0
    assert out["mean"] == pytest.approx((1.0 + 2.5 + 5.0 + 1.0) / 4)
    assert out["max"] == 5.0
    assert out["min"] == 1.0
    # «high» = >1.5: b=2.5, c=5.0 → 2/4 = 0.5.
    assert out["high_pct"] == pytest.approx(0.5)


def test_weight_stats_empty_returns_zeros():
    out = weight_stats({})
    assert out == {"count": 0.0, "mean": 0.0, "max": 0.0, "min": 0.0, "high_pct": 0.0}


# ----- factory: no weights → baseline trainer -----


def test_make_weighted_trainer_class_with_empty_map_falls_back_to_default(monkeypatch):
    """С пустым weights_map factory возвращает родительский класс — без
    попытки импортировать torch/ultralytics.
    """
    # Подменяем импорт ultralytics, чтобы тест не падал на отсутствии пакета.
    class _DummyTrainer:
        pass

    import sys
    import types

    fake_ult = types.ModuleType("ultralytics")
    fake_ult.models = types.ModuleType("ultralytics.models")
    fake_ult.models.yolo = types.ModuleType("ultralytics.models.yolo")
    fake_ult.models.yolo.detect = types.ModuleType("ultralytics.models.yolo.detect")
    fake_ult.models.yolo.detect.DetectionTrainer = _DummyTrainer

    fake_torch = types.ModuleType("torch")
    fake_torch.utils = types.ModuleType("torch.utils")
    fake_torch.utils.data = types.ModuleType("torch.utils.data")
    fake_torch.utils.data.DataLoader = object
    fake_torch.utils.data.WeightedRandomSampler = object

    monkeypatch.setitem(sys.modules, "ultralytics", fake_ult)
    monkeypatch.setitem(sys.modules, "ultralytics.models", fake_ult.models)
    monkeypatch.setitem(sys.modules, "ultralytics.models.yolo", fake_ult.models.yolo)
    monkeypatch.setitem(
        sys.modules, "ultralytics.models.yolo.detect", fake_ult.models.yolo.detect
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch.utils", fake_torch.utils)
    monkeypatch.setitem(sys.modules, "torch.utils.data", fake_torch.utils.data)

    from workers.weighted_training import make_weighted_trainer_class

    cls = make_weighted_trainer_class({})
    assert cls is _DummyTrainer
