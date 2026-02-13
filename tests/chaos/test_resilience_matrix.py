from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services import webhook_dispatcher as wd


class _Resp:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {"items": []}
        self.headers = {"content-type": "application/json"}
        self.text = str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")


def test_chaos_matrix_queue_backlog_alert_assertion(monkeypatch):
    os.environ["OWNER_API_KEY"] = "local-owner-key"
    app = create_app()
    client = TestClient(app)

    monkeypatch.setattr(
        "src.app.workers.rq_queue.get_queue_stats",
        lambda: {
            "queues": {
                "cv": {"depth": 200, "oldest_age_seconds": 75.0},
                "llm": {"depth": 0, "oldest_age_seconds": 0.0},
            }
        },
    )
    r = client.get("/api/v1/jobs/health/queues", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    body = r.json()
    hint = ((body.get("autoscale_hints") or {}).get("cv") or {})
    assert hint.get("scale_up") is True
    assert "depth" in (hint.get("reasons") or [])
    assert "oldest_age" in (hint.get("reasons") or [])

    # Metrics assertion: ensure gauges are set for queue depth/age.
    m = client.get("/metrics")
    assert m.status_code == 200
    body_txt = m.text
    assert 'shopsquire_worker_queue_depth{queue="cv"}' in body_txt
    assert 'shopsquire_worker_queue_oldest_age_seconds{queue="cv"}' in body_txt


def test_chaos_matrix_webhook_retry_storm_to_dlq(monkeypatch):
    class _Down:
        @staticmethod
        def post(*_a, **_k):
            raise RuntimeError("provider_down")

    monkeypatch.setattr(wd, "requests", _Down())
    for i in range(8):
        wd.enqueue_webhook(
            f"matrix-{uuid.uuid4().hex}",
            "https://hooks.invalid/storm",
            {"i": i},
            max_attempts=1,
            tenant_id="matrix-tenant",
        )
    wd.start_worker(poll_interval=0.05)
    time.sleep(0.5)
    wd.stop_worker()
    with db_session() as db:
        rows = db.execute(
            text("SELECT status, COUNT(1) FROM webhook_deliveries WHERE tenant_id=:t GROUP BY status"),
            {"t": "matrix-tenant"},
        ).fetchall()
    counts = {str(r[0]): int(r[1] or 0) for r in (rows or [])}
    assert int(counts.get("dlq", 0)) >= 6

    # Metrics assertion: DLQ counter should have incremented for the target URL.
    app = create_app()
    client = TestClient(app)
    m = client.get("/metrics")
    assert m.status_code == 200
    assert 'shopsquire_webhook_delivery_dlq_total{url="https://hooks.invalid/storm"}' in m.text


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(429, "provider_rate_limited"), (503, "provider_5xx")],
)
def test_chaos_matrix_erp_degradation_assertions(monkeypatch, status_code: int, expected: str):
    os.environ["OWNER_API_KEY"] = "local-owner-key"
    os.environ["NETSUITE_BASE_URL"] = "https://netsuite.example"

    def _request(method, url, params=None, json=None, headers=None, timeout=None):
        _ = method, url, params, json, headers, timeout
        return _Resp(status_code=status_code)

    monkeypatch.setattr("src.app.erp.connectors.netsuite.requests.request", _request)

    app = create_app()
    client = TestClient(app)
    r = client.post(
        "/api/v1/admin/inventory/sync",
        headers={"x-api-key": "local-owner-key"},
        json={"connector": "netsuite", "dry_run": False, "upsert_products": False},
    )
    assert r.status_code == 400
    assert expected in str(r.text)

    # Metrics assertion: webhook counters unaffected here; just ensure metrics endpoint up.
    m = client.get("/metrics")
    assert m.status_code == 200
