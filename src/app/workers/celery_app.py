from __future__ import annotations

import os
from celery import Celery
from kombu import Queue


def make_celery(app_name: str = "shopsquire") -> Celery:
    broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
    backend = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://redis:6379/1"))
    qprefix = str(os.getenv("CELERY_QUEUE_PREFIX", "shopsquire") or "shopsquire").strip()
    default_q = f"{qprefix}.default"
    swarm_q = f"{qprefix}.swarm"
    celery = Celery(app_name, broker=broker, backend=backend)

    signing_enabled = str(os.getenv("CELERY_TASK_SIGNING_ENABLED", "0")).lower() in ("1", "true", "yes")
    if signing_enabled:
        key = str(os.getenv("CELERY_SECURITY_KEY", "") or "").strip()
        cert = str(os.getenv("CELERY_SECURITY_CERTIFICATE", "") or "").strip()
        store = str(os.getenv("CELERY_SECURITY_CERT_STORE", "") or "").strip()
        if key and cert and store:
            celery.conf.update(
                task_serializer="auth",
                accept_content=["auth"],
                result_serializer="json",
                event_serializer="json",
                security_key=key,
                security_certificate=cert,
                security_cert_store=store,
                security_digest="sha256",
            )
            try:
                celery.setup_security()
            except Exception:
                # Fail-safe to json if cert material is invalid.
                celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")
        else:
            celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")
    else:
        celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")

    celery.conf.update(
        timezone="UTC",
        enable_utc=True,
        task_default_queue=default_q,
        task_queues=(Queue(default_q), Queue(swarm_q)),
        task_routes={"src.app.tasks.swarm_tasks.run_swarm": {"queue": swarm_q}},
        task_create_missing_queues=False,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
    )
    return celery


celery_app = make_celery()
