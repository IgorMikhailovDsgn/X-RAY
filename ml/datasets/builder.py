"""Сборка датасетов для дообучения. Использует SQL-запросы из
docs/brainscan_schema.sql (раздел «ÐÐ ÐÐÐÐ Ð« ÐÐÐÐ ÐÐ¡ÐÐ»):

- localize: SELECT из screenshots + localize_annotations
- tumor:    SELECT из localize_images + tumor_annotations

Результат: манифест JSON со списком (image_path, bbox/null, label, source)
заливается в S3 под s3://datasets/{model_type}/v{N}/manifest.json,
регистрируется в таблице `datasets`.

Phase A: stub. Phase B/E: реализация.
"""

from typing import Literal

ModelType = Literal["localize", "tumor"]


def build_dataset(model_type: ModelType) -> str:
    """Соберёт датасет, зальёт манифест в S3, создаст row в datasets.
    Возвращает dataset_id.
    """
    raise NotImplementedError("dataset builder to be implemented in Phase B/E")
