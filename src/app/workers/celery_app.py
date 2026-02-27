from __future__ import annotations

import os
from celery import Celery
from kombu import Queue


def _setup_hmac_signing(celery: Celery) -> None:
    """Configure HMAC-based message content signing as lighter alternative to x509.

    Uses CELERY_HMAC_KEY env var. When set, task payloads are HMAC-SHA256 signed
    and verified on the worker side via a Celery signal handler.
    """
    hmac_key = os.getenv("CELERY_HMAC_KEY", "").strip()
    if not hmac_key:
        # No signing material available at all — use plain JSON
        celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")
        return

    # Store key in app config for signal handler access
    celery.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        _hmac_signing_key=hmac_key,
    )

    from celery.signals import before_task_publish, task_prerun
    import hashlib
    import hmac
    import json as _json

    def _canonical_envelope(*, task_name=None, task_id=None, args=None, kwargs=None) -> bytes:
        payload = {
            "task": str(task_name or ""),
            "id": str(task_id or ""),
            "args": list(args or []),
            "kwargs": dict(kwargs or {}),
        }
        return _json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()

    @before_task_publish.connect
    def _sign_task(headers=None, body=None, **kwargs):
        """Attach HMAC signature to task headers before publishing."""
        key = celery.conf.get("_hmac_signing_key", "")
        if not key or not body:
            return
        hdrs = headers or {}
        b_args = []
        b_kwargs = {}
        try:
            if isinstance(body, (list, tuple)) and len(body) >= 2:
                b_args = body[0] or []
                b_kwargs = body[1] or {}
        except Exception:
            pass
        payload = _canonical_envelope(
            task_name=hdrs.get("task"),
            task_id=hdrs.get("id"),
            args=b_args,
            kwargs=b_kwargs,
        )
        sig = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
        if headers is not None:
            headers["x-hmac-signature"] = sig

    @task_prerun.connect
    def _verify_task(task=None, args=None, kwargs=None, **kw):
        """Verify HMAC signature on worker side before executing task."""
        key = celery.conf.get("_hmac_signing_key", "")
        if not key:
            return
        request = getattr(task, "request", None)
        if request is None:
            return
        # Celery stores custom headers on the request object
        headers = getattr(request, "headers", None) or {}
        provided_sig = headers.get("x-hmac-signature") if isinstance(headers, dict) else None
        if not provided_sig:
            # No signature = unsigned task — reject in strict mode
            import logging
            logging.getLogger("celery_hmac").warning(
                "Unsigned task rejected: %s", getattr(task, "name", "unknown")
            )
            raise RuntimeError("Task message missing HMAC signature — possible injection")

        req_args = getattr(request, "args", args) or []
        req_kwargs = getattr(request, "kwargs", kwargs) or {}
        computed = hmac.new(
            key.encode(),
            _canonical_envelope(
                task_name=getattr(task, "name", ""),
                task_id=getattr(request, "id", ""),
                args=req_args,
                kwargs=req_kwargs,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(str(provided_sig), computed):
            import logging
            logging.getLogger("celery_hmac").error(
                "Task signature mismatch rejected: %s", getattr(task, "name", "unknown")
            )
            raise RuntimeError("Task HMAC signature mismatch — possible tampering")


def make_celery(app_name: str = "shopsquire") -> Celery:
    broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
    backend = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://redis:6379/1"))
    qprefix = str(os.getenv("CELERY_QUEUE_PREFIX", "shopsquire") or "shopsquire").strip()
    default_q = f"{qprefix}.default"
    swarm_q = f"{qprefix}.swarm"
    celery = Celery(app_name, broker=broker, backend=backend)

    # M07: Default to signing-enabled in production environments.
    # In production, unsigned task messages can be injected by compromised Redis.
    _env = str(os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "local")) or "local").strip().lower()
    _default_signing = "1" if _env in ("production", "prod", "staging") else "0"
    signing_enabled = str(os.getenv("CELERY_TASK_SIGNING_ENABLED", _default_signing)).lower() in ("1", "true", "yes")
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
                import logging
                logging.getLogger("celery_app").warning(
                    "Celery task signing setup failed — invalid cert material. "
                    "Falling back to HMAC content signing."
                )
                _setup_hmac_signing(celery)
        else:
            if _env in ("production", "prod", "staging"):
                import logging
                logging.getLogger("celery_app").warning(
                    "CELERY_TASK_SIGNING_ENABLED=1 in production but no cert material provided. "
                    "Set CELERY_SECURITY_KEY, CELERY_SECURITY_CERTIFICATE, CELERY_SECURITY_CERT_STORE. "
                    "Using HMAC content signing as fallback."
                )
            _setup_hmac_signing(celery)
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
