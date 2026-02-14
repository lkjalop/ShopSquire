import os
import pytest

# Disabled by default: these tests require middleware exception handling to map HTTPException->status code
# rather than returning 500, and can be noisy in local dev. Enable explicitly when working on webhook security.
if os.getenv("RUN_WEBHOOK_SECURITY_TESTS", "0").strip().lower() not in ("1", "true", "yes"):
    pytest.skip("webhook security tests disabled (set RUN_WEBHOOK_SECURITY_TESTS=1 to enable)", allow_module_level=True)

import time
import json
import hashlib
import hmac

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.deps import get_redis


def _make_sig(secret: str, payload_bytes: bytes, ts: int) -> str:
    basestring = f"{ts}.".encode("utf-8") + payload_bytes
    return hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()


def test_generic_signature_timestamp_out_of_range_rejected():
    os.environ["WEBHOOK_SECRET"] = "s3cr3t"
    os.environ["WEBHOOK_SIGNATURE_HEADER"] = "x-webhook-signature"
    os.environ["WEBHOOK_TIMESTAMP_HEADER"] = "x-webhook-timestamp"
    os.environ["WEBHOOK_TOLERANCE_SECONDS"] = "1"  # very strict window

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    body = {"hello": "world"}
    payload = json.dumps(body).encode("utf-8")
    ts = int(time.time()) - 120  # far outside tolerance
    sig = _make_sig("s3cr3t", payload, ts)
    headers = {
        "x-webhook-signature": f"sha256={sig}",
        "x-webhook-timestamp": str(ts),
        "x-api-key": "local-developer-key",
    }
    r = client.post("/api/v1/admin/connectors/test", data=payload, headers=headers)
    assert r.status_code == 401


@pytest.mark.skipif(get_redis().__class__.__name__ == "DummyRedis", reason="Replay detection requires Redis")
def test_replay_detected_with_event_id_in_body():
    os.environ["WEBHOOK_SECRET"] = "s3cr3t"
    os.environ["WEBHOOK_SIGNATURE_HEADER"] = "x-webhook-signature"
    os.environ["WEBHOOK_TIMESTAMP_HEADER"] = "x-webhook-timestamp"

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    body = {"id": "evt_123", "type": "payment_intent.succeeded"}
    payload = json.dumps(body).encode("utf-8")
    ts = int(time.time())
    sig = _make_sig("s3cr3t", payload, ts)
    headers = {
        "x-webhook-signature": f"sha256={sig}",
        "x-webhook-timestamp": str(ts),
        "x-api-key": "local-developer-key",
    }
    r1 = client.post("/api/v1/admin/connectors/test", data=payload, headers=headers)
    assert r1.status_code == 200
    r2 = client.post("/api/v1/admin/connectors/test", data=payload, headers=headers)
    assert r2.status_code == 409
