import os

from celery import Celery
from celery.schedules import crontab

APP_ENV = os.environ.get("APP_ENV", "local")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# В non-local средах не доверяем дефолтному адресу redis — он почти наверняка
# не достучится до прод-брокера, и Celery будет молча ретраить впустую.
if APP_ENV != "local" and REDIS_URL == "redis://localhost:6379/0":
    raise RuntimeError(f"REDIS_URL must be set explicitly when APP_ENV={APP_ENV!r}")

app = Celery(
    "brainscan",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["workers.train_localize", "workers.train_tumor", "workers.retrain_trigger"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

# Beat-расписание: раз в сутки проверяем накопление аннотаций и решаем,
# запускать ли дообучение. В MVP реальный train отключён feature-флагом
# ENABLE_REAL_TRAINING — stub-таски логируют запуск и завершаются без работы.
app.conf.beat_schedule = {
    "check-retrain-trigger-localize": {
        "task": "workers.retrain_trigger.check_and_trigger",
        "schedule": crontab(hour=3, minute=0),
        "args": ("localize",),
    },
    "check-retrain-trigger-tumor": {
        "task": "workers.retrain_trigger.check_and_trigger",
        "schedule": crontab(hour=3, minute=15),
        "args": ("tumor",),
    },
}
