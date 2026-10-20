from __future__ import annotations

from copy import deepcopy
import os
from uuid import uuid4

import pytest


@pytest.mark.integration
@pytest.mark.parametrize("forgery", ["unsigned", "bad_signature", "non_ascii_signature", "non_string_signature", "args", "task_id", "schedule", "callbacks"])
def test_celery_runtime_rejects_unsigned_and_bad_signature(monkeypatch, forgery):
    from celery.contrib.testing.worker import start_worker
    from celery.signals import before_task_publish, after_task_publish, task_rejected
    from src.app.workers.celery_app import make_celery

    monkeypatch.setenv("CELERY_BROKER_URL", os.getenv("TEST_CELERY_BROKER_URL", "memory://"))
    monkeypatch.setenv("CELERY_RESULT_BACKEND", os.getenv("TEST_CELERY_RESULT_BACKEND", "cache+memory://"))
    monkeypatch.setenv("CELERY_TASK_SIGNING_ENABLED", "1")
    monkeypatch.setenv("CELERY_HMAC_KEY", "owned-test-key")
    monkeypatch.setenv("CELERY_QUEUE_PREFIX", "owned-signing-" + uuid4().hex)
    monkeypatch.setenv("ENVIRONMENT", "production")
    app = make_celery("owned-signing-" + uuid4().hex)
    app.conf.update(imports=(), beat_schedule={})
    executed = []
    captured = []
    rejected = []

    @app.task(name="owned.echo." + uuid4().hex)
    def echo(value):
        executed.append(value)
        return value

    attempts = []

    @app.task(bind=True, name="owned.retry." + uuid4().hex)
    def retrying(self):
        attempts.append(self.request.retries)
        if self.request.retries == 0:
            raise self.retry(countdown=0, max_retries=1)
        return "retried"

    def capture(sender=None, headers=None, body=None, **kw):
        captured.append((deepcopy(headers), deepcopy(body)))

    def observe_rejection(message=None, **kw):
        rejected.append(message.headers.get("id"))

    def add_trace(headers=None, **kw):
        headers["owned-trace"] = "owned-observer"

    before_task_publish.connect(add_trace, sender=echo.name, weak=False)
    after_task_publish.connect(capture, sender=echo.name, weak=False)
    task_rejected.connect(observe_rejection, weak=False)
    try:
        with start_worker(app, perform_ping_check=False, pool="solo", shutdown_timeout=10):
            assert echo.apply_async(args=("before",), compression="gzip").get(timeout=10) == "before"
            headers, body = captured[-1]
            # Replay the decoded body through JSON, without its former wire codec.
            headers.pop("compression", None)
            if forgery == "unsigned":
                headers.pop("x-hmac-signature", None)
            elif forgery == "bad_signature":
                headers["x-hmac-signature"] = "deadbeef"
            elif forgery == "non_ascii_signature":
                headers["x-hmac-signature"] = chr(0x2603) * 64
            elif forgery == "non_string_signature":
                headers["x-hmac-signature"] = ["invalid"]
            elif forgery == "args":
                body = (("tampered",), body[1], body[2])
            elif forgery == "task_id":
                headers["id"] = uuid4().hex
            elif forgery == "schedule":
                headers["retries"] = 77
            else:
                body[2]["callbacks"] = [dict(echo.s("injected-callback"))]
            injected_id = headers["id"]
            # Publish below the app signer, exactly as a broker-frame injection.
            with app.producer_or_acquire() as producer:
                producer.publish(body, headers=headers, serializer="json", exchange="",
                                 routing_key=app.conf.task_default_queue)
            assert echo.delay("after").get(timeout=10) == "after"
            assert injected_id in rejected, "Worker must reject the injected frame"
            assert executed == ["before", "after"], "Untrusted task body executed"
            if forgery == "callbacks":
                result = (echo.s("legit-chain") | echo.s()).apply_async()
                assert result.get(timeout=10) == "legit-chain"
                assert executed[-2:] == ["legit-chain", "legit-chain"]
                from datetime import datetime, timezone
                value = datetime(2026, 10, 21, tzinfo=timezone.utc)
                assert echo.delay(value).get(timeout=10) == value

                assert retrying.delay().get(timeout=10) == "retried"
                assert attempts == [0, 1]

    finally:
        before_task_publish.disconnect(add_trace, sender=echo.name)
        after_task_publish.disconnect(capture, sender=echo.name)
        task_rejected.disconnect(observe_rejection)
        app.close()
