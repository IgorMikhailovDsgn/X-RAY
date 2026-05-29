"""Ядро реальной тренировки YOLOv8 (Phase 8), общее для localize и tumor.

Поток `run_training(model_type, dataset_id)`:
  1. internal `training/start` → dataset 'ready'→'training', отдаёт manifest_path.
  2. Скачиваем манифест + crop'ы из S3, раскладываем в YOLO-формат.
  3. MLflow start_run (если задан MLFLOW_TRACKING_URI) + log params.
  4. Ultralytics YOLOv8 train → метрики + best.pt.
  5. Заливаем веса в S3, log_artifact/log_metrics в MLflow.
  6. internal `training/complete` → INSERT models(candidate) + dataset 'completed'.
  При ЛЮБОМ исключении на шагах 2-5 → internal `training/fail` (откат dataset +
  освобождение аннотаций) и проброс исключения наверх.

Тяжёлые зависимости (torch/ultralytics/mlflow/PIL) импортируются лениво внутри
функций — модуль грузится дёшево и на CPU-worker'е/в тестах без них.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from workers import _internal_api as api
from workers import s3_io

logger = logging.getLogger(__name__)

# Гиперпараметры — env-override'ятся на GPU-боксе. Дефолты заточены под мелкую
# e2e-выборку (быстрый прогон, nano-бэкбон).
DEFAULT_EPOCHS = int(os.environ.get("TRAIN_EPOCHS", "50"))
DEFAULT_IMGSZ = int(os.environ.get("TRAIN_IMGSZ", "640"))
DEFAULT_BASE_WEIGHTS = os.environ.get("TRAIN_BASE_WEIGHTS", "yolov8n.pt")


def run_training(model_type: str, dataset_id: str) -> dict[str, Any]:
    start = api.training_start(dataset_id)
    version = start["version"]
    manifest_path = start["manifest_path"]
    logger.info(
        "train[%s]: dataset=%s version=%s manifest=%s",
        model_type,
        dataset_id,
        version,
        manifest_path,
    )

    workdir = Path(tempfile.mkdtemp(prefix=f"train_{model_type}_"))
    try:
        manifest = s3_io.download_json(manifest_path)
        data_yaml = _prepare_yolo_dataset(manifest, workdir, class_name=model_type)
        run_id, metrics, best_pt = _train_yolo(
            model_type, version, data_yaml, workdir
        )

        bucket, prefix = s3_io.models_bucket_and_prefix()
        key = f"{prefix}weights/{model_type}/{version}/best.pt"
        artifact_path = s3_io.upload_file(best_pt, bucket, key)
        logger.info("train[%s]: weights uploaded → %s", model_type, artifact_path)

        result = api.training_complete(
            dataset_id,
            artifact_path=artifact_path,
            metrics=metrics,
            mlflow_run_id=run_id,
        )
        logger.info(
            "train[%s]: completed model_id=%s metrics=%s",
            model_type,
            result.get("model_id"),
            metrics,
        )
        return {
            "status": "completed",
            "model_id": result.get("model_id"),
            "version": version,
            "metrics": metrics,
        }
    except Exception as exc:
        logger.exception("train[%s]: failed, rolling back dataset %s", model_type, dataset_id)
        try:
            api.training_fail(dataset_id, reason=f"{type(exc).__name__}: {exc}")
        except Exception:
            logger.exception("train[%s]: rollback call also failed", model_type)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------- YOLO dataset prep ---------------------------


def _prepare_yolo_dataset(
    manifest: dict[str, Any], workdir: Path, *, class_name: str
) -> Path:
    """Раскладывает crop'ы манифеста в YOLO-структуру images/labels/{split} и
    пишет data.yaml. negative-семплы (bbox=None) → пустой label-файл (фон).
    Возвращает путь к data.yaml.
    """
    from PIL import Image

    splits = manifest.get("splits", {})
    non_empty: dict[str, int] = {}
    for split in ("train", "val", "test"):
        samples = splits.get(split, [])
        if not samples:
            continue
        img_dir = workdir / "images" / split
        lbl_dir = workdir / "labels" / split
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for s in samples:
            ann_id = s["annotation_id"]
            img_path = img_dir / f"{ann_id}.png"
            # Crop мог пропасть/побиться в S3 между сборкой манифеста и обучением
            # (или аплоад с клиента не долетел). Пропускаем сэмпл, а не валим весь
            # прогон — обучаемся на доступных.
            try:
                s3_io.download_file(s["crop_path"], img_path)
            except Exception as exc:
                logger.warning(
                    "train: skip %s — crop unavailable (%s): %s",
                    ann_id, s.get("crop_path"), exc,
                )
                continue
            label = _yolo_label(s.get("bbox"), img_path, Image)
            (lbl_dir / f"{ann_id}.txt").write_text(label, encoding="utf-8")
            written += 1
        if written:
            non_empty[split] = written

    if "train" not in non_empty:
        raise RuntimeError("Manifest has no train samples — cannot train")

    # YOLO требует val. Если split пуст на крошечной выборке — валидируем на train.
    val_ref = "images/val" if "val" in non_empty else "images/train"
    data_yaml = workdir / "data.yaml"
    lines = [
        f"path: {workdir}",
        "train: images/train",
        f"val: {val_ref}",
    ]
    if "test" in non_empty:
        lines.append("test: images/test")
    lines.append("names:")
    lines.append(f"  0: {class_name}")
    data_yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("train: YOLO dataset prepared, splits=%s", non_empty)
    return data_yaml


def _yolo_label(bbox: dict[str, Any] | None, img_path: Path, image_mod: Any) -> str:
    """YOLO-строка `0 xc yc w h` (нормированные 0..1) или пусто для негатива."""
    if not bbox:
        return ""
    with image_mod.open(img_path) as im:
        width, height = im.size
    if width <= 0 or height <= 0:
        return ""
    xc = (bbox["x"] + bbox["w"] / 2) / width
    yc = (bbox["y"] + bbox["h"] / 2) / height
    wn = bbox["w"] / width
    hn = bbox["h"] / height
    clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
    return f"0 {clamp(xc):.6f} {clamp(yc):.6f} {clamp(wn):.6f} {clamp(hn):.6f}\n"


# --------------------------- training ---------------------------


def _train_yolo(
    model_type: str, version: str, data_yaml: Path, workdir: Path
) -> tuple[str | None, dict[str, float], Path]:
    """Запускает YOLOv8 train + val. Возвращает (mlflow_run_id, metrics, best_pt)."""
    from ultralytics import YOLO

    # Отключаем встроенную MLflow-интеграцию ultralytics — логируем сами, чтобы
    # не плодить дублирующиеся/вложенные runs.
    try:
        from ultralytics import settings as yolo_settings

        yolo_settings.update({"mlflow": False})
    except Exception:  # best-effort: версия ultralytics может отличаться
        logger.warning("train: couldn't disable ultralytics mlflow integration")

    params = {
        "model_type": model_type,
        "dataset_version": version,
        "base_weights": DEFAULT_BASE_WEIGHTS,
        "epochs": DEFAULT_EPOCHS,
        "imgsz": DEFAULT_IMGSZ,
    }

    mlflow_ctx = _start_mlflow(model_type, params)
    run_id = mlflow_ctx["run_id"] if mlflow_ctx else None
    try:
        model = YOLO(DEFAULT_BASE_WEIGHTS)
        model.train(
            data=str(data_yaml),
            epochs=DEFAULT_EPOCHS,
            imgsz=DEFAULT_IMGSZ,
            project=str(workdir),
            name="run",
            exist_ok=True,
            verbose=False,
            # Celery prefork запускает таску в daemon-процессе, а daemon не может
            # иметь детей → DataLoader с workers>0 падает с AssertionError.
            # workers=0 = загрузка данных в самом процессе (без подпроцессов).
            workers=0,
        )
        val = model.val()
        metrics = {
            "map50": float(val.box.map50),
            "map50_95": float(val.box.map),
            "precision": float(val.box.mp),
            "recall": float(val.box.mr),
        }
        best_pt = workdir / "run" / "weights" / "best.pt"
        if not best_pt.exists():
            raise RuntimeError(f"best.pt not found at {best_pt}")

        if mlflow_ctx:
            import mlflow

            mlflow.log_metrics(metrics)
            mlflow.log_artifact(str(best_pt))
        return run_id, metrics, best_pt
    finally:
        if mlflow_ctx:
            import mlflow

            mlflow.end_run()


def _start_mlflow(model_type: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Стартует MLflow run, если задан MLFLOW_TRACKING_URI. Иначе None (логируем
    только локально — для local-dev и тестов без tracking-сервера).
    """
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        logger.info("train: MLFLOW_TRACKING_URI unset — skipping MLflow logging")
        return None
    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(model_type)
    run = mlflow.start_run()
    mlflow.log_params(params)
    return {"run_id": run.info.run_id}
