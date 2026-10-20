"""App-owned message authentication before broker tasks enter worker execution."""
from __future__ import annotations

import hashlib
import hmac
import os

from celery.exceptions import InvalidTaskError
from celery.worker.request import Request
from kombu.utils.json import dumps


_HEADER = "x-hmac-signature"


def _digest(key, headers, body):
    # These two fields are added by Kombu compression/redelivery, after signing.
    unsigned = {name: value for name, value in headers.items()
                if name not in {_HEADER, "compression", "redelivered"}}
    canonical = dumps({"headers": unsigned, "body": body},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


class AuthenticatedRequest(Request):
    def __init__(self, message, *args, app=None, **kwargs):
        headers = message.headers
        supplied = headers.get(_HEADER)
        key = app.conf.get("_hmac_signing_key", "") if app is not None else ""
        if not key or not isinstance(supplied, str) or len(supplied) != 64 or not supplied.isascii():
            raise InvalidTaskError("Task authentication required")
        expected = _digest(key, headers, message.payload)
        if not hmac.compare_digest(supplied, expected):
            # Rejection at intake prevents scheduling and execution of errbacks.
            raise InvalidTaskError("Task authentication failed")
        super().__init__(message, *args, app=app, **kwargs)


def configure_hmac_signing(app):
    key = os.getenv("CELERY_HMAC_KEY", "").strip()
    if not key:
        raise ValueError("Celery signing requires certificates or CELERY_HMAC_KEY")
    app.conf.update(task_serializer="json", accept_content=["json"],
                    result_serializer="json", task_protocol=2, _hmac_signing_key=key)
    base_task = app.Task

    class AuthenticatedTask(base_task):
        abstract = True
        Request = AuthenticatedRequest

    app.Task = AuthenticatedTask
    original_sender = app.amqp.send_task_message

    class SigningProducer:
        def __init__(self, producer):
            self.producer = producer

        def __getattr__(self, name):
            return getattr(self.producer, name)

        def publish(self, body, headers=None, **options):
            headers = {} if headers is None else headers
            headers[_HEADER] = _digest(key, headers, body)
            return self.producer.publish(body, headers=headers, **options)

    def send_authenticated(producer, name, message, **options):
        # Sign after before_task_publish hooks have added tracing/custom headers.
        return original_sender(SigningProducer(producer), name, message, **options)

    app.amqp.send_task_message = send_authenticated
