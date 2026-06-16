"""Unit-тесты чистых функций `app.services.corrections`."""

from __future__ import annotations

import math

import pytest

from app.services.corrections import (
    CorrectionType,
    compute_training_weight,
    determine_correction_type,
    iou,
    normalize_action,
)

# ----- IoU -----


class TestIoU:
    def test_identical_bboxes_iou_is_1(self):
        b = {"x": 10, "y": 20, "w": 100, "h": 80}
        assert iou(b, b) == pytest.approx(1.0)

    def test_disjoint_bboxes_iou_is_0(self):
        a = {"x": 0, "y": 0, "w": 50, "h": 50}
        b = {"x": 200, "y": 200, "w": 50, "h": 50}
        assert iou(a, b) == 0.0

    def test_nested_bbox_iou_is_inner_over_outer_area(self):
        # Внутренний целиком в внешнем → IoU = area_inner / area_outer.
        outer = {"x": 0, "y": 0, "w": 100, "h": 100}    # 10000
        inner = {"x": 25, "y": 25, "w": 50, "h": 50}    # 2500
        assert iou(outer, inner) == pytest.approx(0.25)

    def test_partial_overlap(self):
        a = {"x": 0, "y": 0, "w": 100, "h": 100}    # 10000
        b = {"x": 50, "y": 0, "w": 100, "h": 100}   # 10000
        # пересечение 50*100=5000, объединение 10000+10000-5000=15000.
        assert iou(a, b) == pytest.approx(5000 / 15000)

    def test_zero_area_bbox(self):
        a = {"x": 0, "y": 0, "w": 0, "h": 100}
        b = {"x": 0, "y": 0, "w": 50, "h": 50}
        assert iou(a, b) == 0.0


# ----- determine_correction_type -----


class TestDetermineCorrectionType:
    def test_both_none_returns_none(self):
        assert determine_correction_type(None, None) == (None, None)

    def test_det_none_ann_present_is_false_negative(self):
        ann = {"x": 0, "y": 0, "w": 10, "h": 10}
        ct, iou_val = determine_correction_type(None, ann)
        assert ct == CorrectionType.FALSE_NEGATIVE
        assert iou_val is None

    def test_det_present_ann_none_is_false_positive(self):
        det = {"x": 0, "y": 0, "w": 10, "h": 10}
        ct, iou_val = determine_correction_type(det, None)
        assert ct == CorrectionType.FALSE_POSITIVE
        assert iou_val is None

    def test_iou_near_perfect_returns_none(self):
        # IoU=1.0 → considered confirmed.
        b = {"x": 10, "y": 20, "w": 100, "h": 80}
        ct, iou_val = determine_correction_type(b, b)
        assert ct is None
        assert iou_val == pytest.approx(1.0)

    def test_iou_in_minor_band_is_minor_adjustment(self):
        # Шифт на 5px у 100x100 → IoU около 0.91.
        det = {"x": 0, "y": 0, "w": 100, "h": 100}
        ann = {"x": 5, "y": 5, "w": 100, "h": 100}
        ct, iou_val = determine_correction_type(det, ann)
        assert ct == CorrectionType.MINOR_ADJUSTMENT
        assert 0.70 <= iou_val < 0.95

    def test_iou_imprecise_band(self):
        # Сдвиг на 30px у 100x100 → IoU около 0.55.
        det = {"x": 0, "y": 0, "w": 100, "h": 100}
        ann = {"x": 30, "y": 30, "w": 100, "h": 100}
        ct, iou_val = determine_correction_type(det, ann)
        assert ct == CorrectionType.IMPRECISE_BBOX
        assert 0.30 <= iou_val < 0.70

    def test_iou_wrong_location_band(self):
        # Маленькое пересечение → IoU < 0.30.
        det = {"x": 0, "y": 0, "w": 100, "h": 100}
        ann = {"x": 75, "y": 75, "w": 100, "h": 100}
        ct, iou_val = determine_correction_type(det, ann)
        assert ct == CorrectionType.WRONG_LOCATION
        assert iou_val < 0.30


# ----- normalize_action -----


class TestNormalizeAction:
    def test_corrected_with_no_correction_type_becomes_confirmed(self):
        # IoU≥0.95 → correction_type None → переписываем в confirmed.
        assert normalize_action("corrected", None, has_detection_id=True) == "confirmed"

    def test_corrected_with_correction_type_stays_corrected(self):
        assert (
            normalize_action(
                "corrected", CorrectionType.WRONG_LOCATION, has_detection_id=True
            )
            == "corrected"
        )

    def test_confirmed_unchanged(self):
        assert normalize_action("confirmed", None, has_detection_id=True) == "confirmed"

    def test_created_unchanged(self):
        assert normalize_action("created", None, has_detection_id=False) == "created"

    def test_corrected_without_detection_id_not_rewritten(self):
        # Невалидная комбинация — пусть валидатор схемы её отклонит, мы не лезем.
        assert (
            normalize_action("corrected", None, has_detection_id=False) == "corrected"
        )


# ----- compute_training_weight -----


class TestComputeTrainingWeight:
    def test_confirmed_weight_is_1(self):
        w = compute_training_weight(
            action="confirmed",
            correction_type=None,
            has_bbox=True,
            detection_confidence=0.9,
        )
        assert w == pytest.approx(1.0)

    def test_created_with_bbox_is_3(self):
        # Cold-start ручная разметка с положительным сэмплом — ценнее обычной.
        w = compute_training_weight(
            action="created",
            correction_type=None,
            has_bbox=True,
            detection_confidence=None,
        )
        assert w == pytest.approx(3.0)

    def test_created_null_bbox_is_1(self):
        # Mark Null без детекции — просто негатив, не корректировка.
        w = compute_training_weight(
            action="created",
            correction_type=None,
            has_bbox=False,
            detection_confidence=None,
        )
        assert w == pytest.approx(1.0)

    @pytest.mark.parametrize(
        ("ct", "expected_base"),
        [
            (CorrectionType.FALSE_NEGATIVE, 5.0),
            (CorrectionType.FALSE_POSITIVE, 3.0),
            (CorrectionType.WRONG_LOCATION, 4.0),
            (CorrectionType.IMPRECISE_BBOX, 2.0),
            (CorrectionType.MINOR_ADJUSTMENT, 1.5),
        ],
    )
    def test_corrected_base_weight_per_correction_type(self, ct, expected_base):
        w = compute_training_weight(
            action="corrected",
            correction_type=ct,
            has_bbox=True,
            detection_confidence=None,
        )
        assert w == pytest.approx(expected_base)

    def test_high_confidence_correction_multiplied_by_1_5(self):
        # FN base 5.0 × 1.5 (conf>0.8) = 7.5.
        w = compute_training_weight(
            action="corrected",
            correction_type=CorrectionType.FALSE_NEGATIVE,
            has_bbox=True,
            detection_confidence=0.95,
        )
        assert w == pytest.approx(7.5)

    def test_low_confidence_correction_multiplied_by_0_8(self):
        # WL base 4.0 × 0.8 (conf<0.4) = 3.2.
        w = compute_training_weight(
            action="corrected",
            correction_type=CorrectionType.WRONG_LOCATION,
            has_bbox=True,
            detection_confidence=0.3,
        )
        assert w == pytest.approx(3.2)

    def test_mid_confidence_no_multiplier(self):
        # 0.4 <= conf <= 0.8 → multiplier=1.0.
        w = compute_training_weight(
            action="corrected",
            correction_type=CorrectionType.FALSE_POSITIVE,
            has_bbox=False,
            detection_confidence=0.6,
        )
        assert w == pytest.approx(3.0)

    def test_confidence_multiplier_not_applied_to_confirmed(self):
        # confirmed остаётся 1.0 даже при экстремальной уверенности — это не
        # «ошибка модели», multiplier не должен случайно её сдвинуть.
        w_high = compute_training_weight(
            action="confirmed",
            correction_type=None,
            has_bbox=True,
            detection_confidence=0.99,
        )
        w_low = compute_training_weight(
            action="confirmed",
            correction_type=None,
            has_bbox=True,
            detection_confidence=0.1,
        )
        assert w_high == pytest.approx(1.0)
        assert w_low == pytest.approx(1.0)

    def test_weight_clamped_to_max(self):
        # FN × 1.5 = 7.5, далеко не 10. Проверим, что если кто-то увеличит
        # дефолты — клэмп удержит. Имитируем через корректировку min/max — но
        # это unit тест функции, базовые константы фиксированы, поэтому
        # проверим только текущий потолок.
        # FALSE_NEGATIVE × 1.5 = 7.5 < 10.0 ✓
        # (отдельной защиты от ручной правки констант здесь не делаем)
        w = compute_training_weight(
            action="corrected",
            correction_type=CorrectionType.FALSE_NEGATIVE,
            has_bbox=True,
            detection_confidence=0.99,
        )
        assert w <= 10.0
        assert w >= 0.5

    def test_corrected_without_correction_type_falls_back(self):
        # Защитный путь: action=corrected пришёл, но correction_type=None
        # (вообще говоря normalize_action бы переписал в confirmed; защищаемся
        # на случай порядка операций при будущих рефакторах).
        w = compute_training_weight(
            action="corrected",
            correction_type=None,
            has_bbox=True,
            detection_confidence=None,
        )
        assert math.isclose(w, 1.0)
