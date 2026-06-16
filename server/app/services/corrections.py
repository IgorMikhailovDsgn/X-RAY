"""Correction-сигналы от обратной связи врача → weighted training.

Чистые функции, без I/O. Используются в:
- `/api/v1/localize-annotations`, `/tumor-annotations`, `/detect/annotations`
  (Stage A.4, A.6): при INSERT'е аннотации сервер вычисляет correction_type,
  iou_with_detection, training_weight и пишет денормализованно в строку.
- Тренировка позже считывает `training_weight` из манифеста как множитель loss.

Логика устроена так, что **сервер — единственное место принятия решений** про
итоговый action и correction_type. Клиент шлёт интент (`confirmed`/`corrected`/
`created`) + сырые bbox'ы; сервер при необходимости переписывает
`corrected→confirmed` (при IoU≥0.95) и формирует все денормализованные поля.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class CorrectionType(str, Enum):  # noqa: UP042 — str+Enum (legacy) над StrEnum для совместимости
    """Категории ошибок модели. Хранится в `*_annotations.correction_type`."""

    FALSE_NEGATIVE = "false_negative"     # модель пропустила → врач нашёл
    FALSE_POSITIVE = "false_positive"     # модель показала → врач говорит «нет»
    WRONG_LOCATION = "wrong_location"     # модель нашла, но в неправильном месте
    IMPRECISE_BBOX = "imprecise_bbox"     # модель близка, но границы неточные
    MINOR_ADJUSTMENT = "minor_adjustment"  # практически совпадает


# IoU-пороги — фиксированы здесь, выноса в БД-настройки сейчас не делаем
# (см. соответствующий TODO в gates.py — тот же подход).
IOU_NEAR_PERFECT = 0.95   # corrected с таким IoU → переписываем в confirmed
IOU_MINOR_BAND = 0.70     # >= порог → MINOR_ADJUSTMENT
IOU_IMPRECISE = 0.30      # >= порог → IMPRECISE_BBOX; иначе WRONG_LOCATION


# Базовые веса. Соответствуют спеке Igor'а.
_BASE_WEIGHT_CONFIRMED = 1.0
_BASE_WEIGHT_CREATED_POSITIVE = 3.0   # врач разметил с нуля — ценнее обычного
_BASE_WEIGHT_CREATED_NEGATIVE = 1.0   # Mark Null без детекции — просто негатив
_BASE_WEIGHT_BY_CORRECTION: dict[CorrectionType, float] = {
    CorrectionType.FALSE_NEGATIVE: 5.0,
    CorrectionType.FALSE_POSITIVE: 3.0,
    CorrectionType.WRONG_LOCATION: 4.0,
    CorrectionType.IMPRECISE_BBOX: 2.0,
    CorrectionType.MINOR_ADJUSTMENT: 1.5,
}

# Multiplier по детекционной уверенности: «уверена и ошиблась» наказывается
# жёстче, «сама сомневалась» — мягче.
_CONF_HIGH_THRESHOLD = 0.8
_CONF_LOW_THRESHOLD = 0.4
_CONF_HIGH_MULTIPLIER = 1.5
_CONF_LOW_MULTIPLIER = 0.8

# Защита от экстремальных весов: даже при FN+high-conf (5×1.5=7.5) укладываемся,
# но клэмп ловит регрессии в формулах.
WEIGHT_MIN = 0.5
WEIGHT_MAX = 10.0


def iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    """IoU двух bbox в формате `{x, y, w, h}` (целые пиксели). Если bbox
    нулевой площади или нет пересечения — 0.0.
    """
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = ax1 + a["w"], ay1 + a["h"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = bx1 + b["w"], by1 + b["h"]

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter == 0:
        return 0.0

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def determine_correction_type(
    det_bbox: dict[str, Any] | None,
    ann_bbox: dict[str, Any] | None,
) -> tuple[CorrectionType | None, float | None]:
    """Возвращает (correction_type, iou_value).

    Случаи:
      det=None,    ann=None    → (None, None)  -- врач подтвердил «нет»
      det=None,    ann≠None    → (FALSE_NEGATIVE, None)
      det≠None,    ann=None    → (FALSE_POSITIVE, None)
      оба ≠None и IoU>=0.95    → (None, iou)   -- фактически confirmed
      0.70 <= IoU < 0.95       → (MINOR_ADJUSTMENT, iou)
      0.30 <= IoU < 0.70       → (IMPRECISE_BBOX, iou)
      IoU < 0.30               → (WRONG_LOCATION, iou)
    """
    if det_bbox is None and ann_bbox is None:
        return None, None
    if det_bbox is None and ann_bbox is not None:
        return CorrectionType.FALSE_NEGATIVE, None
    if det_bbox is not None and ann_bbox is None:
        return CorrectionType.FALSE_POSITIVE, None
    # mypy: оба не None.
    assert det_bbox is not None and ann_bbox is not None
    iou_value = iou(det_bbox, ann_bbox)
    if iou_value >= IOU_NEAR_PERFECT:
        return None, iou_value
    if iou_value >= IOU_MINOR_BAND:
        return CorrectionType.MINOR_ADJUSTMENT, iou_value
    if iou_value >= IOU_IMPRECISE:
        return CorrectionType.IMPRECISE_BBOX, iou_value
    return CorrectionType.WRONG_LOCATION, iou_value


def normalize_action(
    client_action: str,
    correction_type: CorrectionType | None,
    has_detection_id: bool,
) -> str:
    """Сервер переписывает клиентский action на основе фактических данных:

    - `corrected` + correction_type=None (IoU≥0.95) → `confirmed`.
      Клиент просил «это исправление», но фактически bbox практически совпал
      с предсказанием модели — записываем как confirmed.
    - `confirmed` без `detection_id` → нелегитимно, но валидаторы схем уже
      такой запрос отклонят; функция возвращает действие как есть.

    Остальные случаи возвращаются без изменений.
    """
    if client_action == "corrected" and correction_type is None and has_detection_id:
        return "confirmed"
    return client_action


def compute_signals(
    *,
    client_action: str,
    ann_bbox: dict[str, Any] | None,
    detection_bbox: dict[str, Any] | None,
    detection_confidence: float | None,
    has_detection: bool,
) -> tuple[str, str | None, float | None, float]:
    """High-level helper для endpoint'ов: одна точка вычисления всех денорм-полей.

    Принимает:
      - `client_action` — интент клиента ('confirmed' | 'corrected' | 'created').
      - `ann_bbox` — bbox аннотации (или None для Mark Null).
      - `detection_bbox`, `detection_confidence` — из БД соответствующей детекции
        (None если детекции нет: cold-start или action='created').
      - `has_detection` — флаг «detection_id передан в запросе».

    Возвращает кортеж `(final_action, correction_type_value, iou, weight)`,
    готовый к INSERT'у в таблицу. `correction_type_value` — строка из
    `CorrectionType.value` либо None (для COLUMN значения).
    """
    if has_detection:
        correction_type, iou_value = determine_correction_type(detection_bbox, ann_bbox)
    else:
        # Без детекции correction_type не применим (cold-start, Mark Null
        # вне детекта). normalize_action в этом режиме ничего не переписывает.
        correction_type, iou_value = None, None

    final_action = normalize_action(
        client_action, correction_type, has_detection_id=has_detection
    )
    weight = compute_training_weight(
        action=final_action,
        correction_type=correction_type,
        has_bbox=ann_bbox is not None,
        detection_confidence=detection_confidence,
    )
    return (
        final_action,
        correction_type.value if correction_type is not None else None,
        iou_value,
        weight,
    )


def compute_training_weight(
    *,
    action: str,
    correction_type: CorrectionType | None,
    has_bbox: bool,
    detection_confidence: float | None,
) -> float:
    """Финальный вес для weighted training. Клэмпится в [WEIGHT_MIN, WEIGHT_MAX].

    Args:
        action: финальный action ПОСЛЕ `normalize_action` (confirmed / corrected
                / created).
        correction_type: для corrected — категория ошибки. Иначе None.
        has_bbox: bbox у аннотации не NULL.
        detection_confidence: уверенность детекции (0..1) или None если нет
                              детекции (cold-start) либо historical row.
    """
    if action == "confirmed":
        base = _BASE_WEIGHT_CONFIRMED
    elif action == "created":
        base = (
            _BASE_WEIGHT_CREATED_POSITIVE if has_bbox else _BASE_WEIGHT_CREATED_NEGATIVE
        )
    elif action == "corrected":
        if correction_type is None:
            # Защита: corrected без correction_type теоретически невозможен,
            # т.к. normalize_action переписал бы его в confirmed. Если попали
            # сюда — даём базовый вес, лучше консервативнее.
            base = _BASE_WEIGHT_CONFIRMED
        else:
            base = _BASE_WEIGHT_BY_CORRECTION[correction_type]
    else:
        # Незнакомый action — sanity-fallback.
        base = _BASE_WEIGHT_CONFIRMED

    multiplier = 1.0
    # Confidence-multiplier применяется ТОЛЬКО когда модель ошиблась и мы
    # знаем её уверенность. Для confirmed/created это шум.
    if (
        detection_confidence is not None
        and action == "corrected"
        and correction_type is not None
    ):
        if detection_confidence > _CONF_HIGH_THRESHOLD:
            multiplier = _CONF_HIGH_MULTIPLIER
        elif detection_confidence < _CONF_LOW_THRESHOLD:
            multiplier = _CONF_LOW_MULTIPLIER

    return max(WEIGHT_MIN, min(WEIGHT_MAX, base * multiplier))
