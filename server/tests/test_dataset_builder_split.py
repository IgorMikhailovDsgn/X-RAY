"""Unit-тесты для `_group_shuffle_split` — без БД, проверяют anti-leakage
и детерминизм по seed."""

from __future__ import annotations

from app.services.dataset_builder import _group_shuffle_split


def _make_samples(groups: list[str]) -> list[dict]:
    return [
        {
            "annotation_id": f"ann-{i}",
            "screen_id": g,
            "crop_path": "x",
            "label": "localize",
            "bbox": {"x": i, "y": 0, "w": 1, "h": 1},
            "annotator_id": "a",
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
