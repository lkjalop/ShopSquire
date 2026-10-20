"""Configuration and app-isolation controls around broker authentication."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from celery.exceptions import InvalidTaskError


@pytest.mark.parametrize("environment", ["local", "staging", "production"])
def test_enabled_signing_requires_key(monkeypatch, environment):
    from src.app.workers.celery_app import make_celery

    monkeypatch.setenv("CELERY_TASK_SIGNING_ENABLED", "1")
    monkeypatch.setenv("ENVIRONMENT", environment)
    for name in ("CELERY_HMAC_KEY", "CELERY_SECURITY_KEY", "CELERY_SECURITY_CERTIFICATE",
                 "CELERY_SECURITY_CERT_STORE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="signing requires"):
        make_celery("no-key-" + uuid4().hex)


def test_app_producers_use_their_own_keys_and_do_not_register_global_hooks(monkeypatch):
    from celery.signals import before_task_publish, task_prerun
    from src.app.workers.celery_app import make_celery
    from src.app.workers.task_signing import AuthenticatedRequest

    apps = []
    monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "cache+memory://")
    monkeypatch.setenv("CELERY_TASK_SIGNING_ENABLED", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")
    hooks = (list(before_task_publish.receivers), list(task_prerun.receivers))
    frames = []

    class Producer:
        def publish(self, body, headers=None, **kwargs):
            frames.append((deepcopy(headers), deepcopy(body)))

    try:
        for key in ("owned-key-a", "owned-key-b"):
            monkeypatch.setenv("CELERY_HMAC_KEY", key)
            apps.append(make_celery("own-key-" + uuid4().hex))
        for app in apps:
            message = app.amqp.create_task_message("same-id", "owned.echo", args=("safe",))
            app.amqp.send_task_message(Producer(), "owned.echo", message)
        assert frames[0][0]["x-hmac-signature"] != frames[1][0]["x-hmac-signature"]
        assert hooks == (list(before_task_publish.receivers), list(task_prerun.receivers))
        for app, (headers, body) in zip(apps, frames):
            class Message:
                payload = body
            message = Message()
            message.headers = headers
            other = apps[1] if app is apps[0] else apps[0]
            with pytest.raises(InvalidTaskError, match="authentication failed"):
                AuthenticatedRequest(message, app=other)
    finally:
        for app in apps:
            app.close()


def test_signature_normalizes_typed_json_and_transport_headers():
    from datetime import datetime, timezone
    from kombu.utils.json import dumps, loads
    from src.app.workers.task_signing import _digest

    headers = {"task": "owned.echo", "id": "owned-task"}
    body = ((datetime(2026, 10, 21, tzinfo=timezone.utc),), {}, {})
    expected = _digest("test-only", headers, body)
    delivered = loads(dumps(body))
    delivered_headers = dict(headers, compression="application/x-gzip", redelivered=True)
    assert _digest("test-only", delivered_headers, delivered) == expected
    delivered_headers["retries"] = 100
    assert _digest("test-only", delivered_headers, delivered) != expected
