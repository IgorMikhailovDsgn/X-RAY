"""Минимальный Celery-клиент в server'е — для send_task'а из admin-endpoint'ов.

Сервер не определяет таски, только их кидает в Redis-broker по имени. Сами
таски определяет ml-worker (`workers.train_*.train` и пр.). В прод-сценарии
Phase 7+ запросы пойдут в очередь `gpu`, которую слушает отдельный GPU-worker;
сейчас (до Phase 7) роутинга нет — таски падают в `default` queue, дев-worker
их подбирает, train-стаб логирует "skipped" и возвращает (без шума).

В тестах monkeypatch'им `send_train_task` — реальное подключение к Redis нам
там ни к чему.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from celery import Celery

from app.config import settings


@lru_cache(maxsize=1)
def get_celery() -> Celery:
    # backend нам не нужен — мы только публикуем таски, результаты не читаем.
    return Celery(broker=settings.redis_url)


def send_train_task(model_type: str, dataset_id: uuid.UUID) -> str:
    """Отправляет задачу обучения, возвращает celery_task_id для аудита.

    queue='gpu' задаём явно: task_routes из ml/workers/celery_app.py на server'е
    не загружены (server только публикует), поэтому без явной очереди таска ушла
    бы в дефолтную 'celery', которую GPU-worker (слушает 'gpu') не разбирает —
    и обучение бы не стартовало.
    """
    app = get_celery()
    result = app.send_task(
        f"workers.train_{model_type}.train", args=[str(dataset_id)], queue="gpu"
    )
    return result.id
