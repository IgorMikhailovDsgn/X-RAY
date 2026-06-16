"""Unit-тесты для `_group_shuffle_split` — без БД, проверяют anti-leakage
и детерминизм по seed.

Также: денормализованная сводка manifest.stats (Phase 10): by_correction_type
+ weight_distribution.
"""

from __future__ import annotations

import pytest

from app.services.dataset_builder import (
    _by_correction_type,
    _group_shuffle_split,
    _manifest_sample,
    _weight_distribution,
)


def _make_samples(
    groups: list[str],
    *,
    weights: list[float] | None = None,
    correction_types: list[str | None] | None = None,
) -> list[dict]:
    n = len(groups)
    weights = weights or [1.0] * n
    correction_types = correction_types or [None] * n
    return [
        {
            "annotation_id": f"ann-{i}",
            "screen_id": g,
            "crop_path": "x",
            "label": "localize",
            "bbox": {"x": i, "y": 0, "w": 1, "h": 1},
            "annotator_id": "a",
            "correction_type": correction_types[i],
            "training_weight": weights[i],
        }
        for i, g in enumerate(groups)
    ]


def test_split_anti_leakage_by_screen():
    # 10 групп, каждая по 3 sample'а — итого 30.
    groups = [f"s{g}" for g in range(10) for _ in range(3)]
    samples = _make_samples(groups)
    tr, va, te = _group_shuffle_split(samples, seed=42)
    all_idx = tr + va + te
    assert sorted(all_idx) == list(range(30)), "split не покрыл все samples"
    # Ни одна группа не должна оказаться в двух split'ах.
    tr_groups = {samples[i]["screen_id"] for i in tr}
    va_groups = {samples[i]["screen_id"] for i in va}
    te_groups = {samples[i]["screen_id"] for i in te}
    assert tr_groups.isdisjoint(va_groups)
    assert tr_groups.isdisjoint(te_groups)
    assert va_groups.isdisjoint(te_groups)


def test_split_deterministic_by_seed():
    groups = [f"s{g}" for g in range(20)]
    samples = _make_samples(groups)
    a = _group_shuffle_split(samples, seed=7)
    b = _group_shuffle_split(samples, seed=7)
    assert a == b, "split не воспроизводим при одинаковом seed"


def test_split_changes_with_seed():
    groups = [f"s{g}" for g in range(20)]
    samples = _make_samples(groups)
    a = _group_shuffle_split(samples, seed=1)
    b = _group_shuffle_split(samples, seed=2)
    assert a != b, "разные seed'ы дают одинаковый split — что-то сломано"


def test_split_handles_two_samples():
    # Edge-case: 2 группы, 1 sample каждая. train_n=max(1,...)=1, val_n=0, test=1.
    samples = _make_samples(["s0", "s1"])
    tr, va, te = _group_shuffle_split(samples, seed=42)
    assert len(tr) == 1
    assert len(te) == 1
    assert len(va) == 0


# ----- Phase 10: by_correction_type + weight_distribution + manifest_sample -----


def test_by_correction_type_groups_with_none_bucket():
    samples = _make_samples(
        ["s0", "s0", "s1", "s1", "s2"],
        correction_types=[
            "false_negative", "wrong_location", "false_negative", None, None
        ],
    )
    out = _by_correction_type(samples)
    assert out == {"false_negative": 2, "wrong_location": 1, "none": 2}


def test_weight_distribution_basic_stats():
    samples = _make_samples(
        ["s0"] * 5,
        weights=[1.0, 2.0, 3.0, 4.0, 5.0],
    )
    d = _weight_distribution(samples)
    assert d["mean"] == pytest.approx(3.0)
    assert d["median"] == pytest.approx(3.0)
    assert d["min"] == pytest.approx(1.0)
    assert d["max"] == pytest.approx(5.0)
    assert d["p25"] == pytest.approx(2.0)
    assert d["p75"] == pytest.approx(4.0)


def test_weight_distribution_empty_returns_zeros():
    assert _weight_distribution([])["mean"] == 0.0


def test_manifest_sample_propagates_weight_and_correction_type():
    samples = _make_samples(
        ["s0"],
        weights=[4.5],
        correction_types=["false_positive"],
    )
    out = _manifest_sample(samples[0])
    assert out["training_weight"] == pytest.approx(4.5)
    assert out["correction_type"] == "false_positive"
    assert out["annotation_id"] == "ann-0"
