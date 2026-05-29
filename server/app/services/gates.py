"""Gate-условия готовности dataset'а к тренировке.

Хардкодные пороги per `model_type`. Идея: не пускать тренировку если выборка
гарантированно плоха (мало, все от одного annotator'а, нет negatives).

В будущем (`system_settings.gate_thresholds` JSONB) можно вынести в БД, чтобы
крутить без redeploy'а — но только когда первый раз потребуется крутить.
"""

from __future__ import annotations

from typing import TypedDict

from app.services.dataset_stats import DatasetStats, ModelType


class GateThresholds(TypedDict):
    min_total: int
    min_positive: int
    min_negative: int
    min_annotators: int
    max_annotator_pct: float


# Пороги временно снижены под solo-annotator e2e-тест (2026-05-29): Igor —
# единственный разметчик, сделает ~100 скринов; цель — прогнать весь пайплайн
# (build → manifest → GPU → train → model), а не качество выборки. Перед реальным
# обучением вернуть к боевым значениям (localize 500/150/50/2/70, tumor 300/120/30/2/70).
# min_negative=0: без задеплоенной модели Annotate-флоу даёт только
# action='created' (bbox обязателен → positive). Negatives (bbox=NULL) требуют
# action='confirmed' с detection_id, а детекций нет, пока нет prod-модели. Так
# что для первого e2e-датасета все аннотации positive — не блокируем.
GATE_THRESHOLDS: dict[str, GateThresholds] = {
    "localize": {
        "min_total": 50,
        "min_positive": 15,
        "min_negative": 0,
        "min_annotators": 1,
        "max_annotator_pct": 100.0,
    },
    "tumor": {
        "min_total": 50,
        "min_positive": 15,
        "min_negative": 0,
        "min_annotators": 1,
        "max_annotator_pct": 100.0,
    },
}


def evaluate_gates(
    stats: DatasetStats, model_type: ModelType
) -> tuple[bool, list[str]]:
    """Возвращает (passed, issues). issues — человекочитаемые сообщения для
    UI/логов, не машинные коды.
    """
    t = GATE_THRESHOLDS[model_type]
    issues: list[str] = []
    if stats.total_free < t["min_total"]:
        issues.append(
            f"Свободных аннотаций {stats.total_free} < {t['min_total']} (min_total)"
        )
    if stats.positive < t["min_positive"]:
        issues.append(
            f"Positive {stats.positive} < {t['min_positive']} (min_positive)"
        )
    if stats.negative < t["min_negative"]:
        issues.append(
            f"Negative {stats.negative} < {t['min_negative']} (min_negative)"
        )
    if stats.unique_annotators < t["min_annotators"]:
        issues.append(
            f"Annotator'ов {stats.unique_annotators} < {t['min_annotators']} "
            f"(min_annotators) — bias-риск"
        )
    if stats.max_annotator_pct > t["max_annotator_pct"]:
        issues.append(
            f"Один annotator сделал {stats.max_annotator_pct}% выборки "
            f"(>{t['max_annotator_pct']}% порог)"
        )
    return (len(issues) == 0, issues)
