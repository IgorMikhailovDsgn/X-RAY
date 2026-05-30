"""CPU inference для /detect (Phase 9, подход A — torch CPU прямо в server-образе).

Lazy-load deployed prod-моделей в память процесса (LRU-кэш по model_id).
Веса скачиваются из S3 один раз в /tmp/<model_id>.pt; YOLO держит распакованные
веса в RAM. Тяжёлые импорты (torch/ultralytics/PIL) — ленивые внутри функций,
чтобы import модуля был дёшев в тестах с mocked-инференсом.

Inference синхронный/CPU-bound → оборачиваем в `asyncio.to_thread`, чтобы не
блокировать event loop FastAPI.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from app.storage import get_s3_client

logger = logging.getLogger(__name__)

_CACHE_DIR = os.environ.get("INFERENCE_CACHE_DIR", "/tmp/brainscan-inference")
_CONF_THRESHOLD = float(os.environ.get("INFERENCE_CONF_THRESHOLD", "0.25"))


def _download_weights(model_id: str, artifact_path: str) -> str:
    """Скачивает best.pt из S3 один раз в локальный кэш, возвращает путь."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    local = os.path.join(_CACHE_DIR, f"{model_id}.pt")
    if os.path.exists(local):
        return local
    u = urlparse(artifact_path)
    bucket, key = u.netloc, u.path.lstrip("/")
    get_s3_client().raw.download_file(bucket, key, local)
    logger.info("inference: cached weights %s → %s", artifact_path, local)
    return local


@lru_cache(maxsize=4)
def _load_model(model_id: str, artifact_path: str) -> Any:
    """Lazy-load YOLO. Кэш на 4 модели (для текущего MVP хватает 2 — localize+tumor)."""
    from ultralytics import YOLO

    path = _download_weights(model_id, artifact_path)
    return YOLO(path)


def _predict_top_bbox(
    model_id: str, artifact_path: str, image_bytes: bytes
) -> dict[str, Any] | None:
    """Inference на одном image_bytes, возвращает top-confidence bbox или None."""
    from PIL import Image

    model = _load_model(model_id, artifact_path)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    results = model.predict(source=img, verbose=False, conf=_CONF_THRESHOLD)
    if not results:
        return None
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None
    confs = boxes.conf.cpu().numpy()
    top = int(confs.argmax())
    x1, y1, x2, y2 = boxes.xyxy[top].cpu().numpy().tolist()
    return {
        "x": max(0, round(x1)),
        "y": max(0, round(y1)),
        "w": max(1, round(x2 - x1)),
        "h": max(1, round(y2 - y1)),
        "confidence": float(confs[top]),
    }


async def predict(model_id: str, artifact_path: str, image_bytes: bytes) -> dict[str, Any] | None:
    """Async-обёртка над синхронным inference (CPU-bound)."""
    return await asyncio.to_thread(_predict_top_bbox, model_id, artifact_path, image_bytes)


def crop_png(image_bytes: bytes, bbox: dict[str, Any]) -> bytes:
    """Crop PNG по bbox (x,y,w,h в пикселях); возвращает PNG-байты."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    crop = img.crop((x, y, x + w, y + h))
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()
