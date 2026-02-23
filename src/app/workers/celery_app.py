from __future__ import annotations

import os
from celery import Celery


def make_celery(app_name: str = "shopsquire") -> Celery:
    broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
    backend = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://redis:6379/1"))
    celery = Celery(app_name, broker=broker, backend=backend)
    celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json", timezone="UTC", enable_utc=True)
    return celery


celery_app = make_celery()
