from __future__ import annotations

import os
import time
import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_security_event_ingest_correlation_and_ticketing():
    client = TestClient(create_app())
    run = uuid.uuid4().hex[:10]
    trace_id = f"trace-corr-{run}"
    tenant_id = f"tenant-a-{run}"
    p1 = {
        "vendor": "crowdstrike",
        "event": {
            "detection_id": f"det-corr-{run}-1",
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "event_type": "network",
            "severity": "high",
            "confidence": 0.81,
        },
    }
    r1 = client.post("/api/v1/security/events/ingest", headers={"x-api-key": "local-owner-key"}, json=p1)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert (j1.get("correlation") or {}).get("event_count") == 1
    assert j1.get("ticket") is not None

    p2 = {
        "vendor": "firewall",
        "event": {
            "log_id": f"fw-corr-{run}-1",
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "action": "deny",
            "severity": "high",
        },
    }
    r2 = client.post("/api/v1/security/events/ingest", headers={"x-api-key": "local-owner-key"}, json=p2)
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    corr = j2.get("correlation") or {}
    assert int(corr.get("event_count") or 0) >= 2
    assert bool(corr.get("multi_source")) is True


def test_security_event_ingest_chaos_missing_duplicate_out_of_order():
    client = TestClient(create_app())
    run = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-z-{run}"
    trace_1 = f"trace-chaos-{run}-1"
    trace_2 = f"trace-chaos-{run}-2"
    missing = client.post(
        "/api/v1/security/events/ingest",
        headers={"x-api-key": "local-owner-key"},
        json={"vendor": "siem", "event": {"tenant_id": tenant_id}},
    )
    assert missing.status_code == 200, missing.text
    assert missing.json().get("ok") is True

    dup_payload = {
        "vendor": "siem",
        "event": {
            "event_id": "dup-1",
            "trace_id": trace_1,
            "tenant_id": tenant_id,
            "event_time": "2026-01-01T00:00:00Z",
            "severity": "medium",
            "confidence": 0.51,
            "type": "network",
        },
    }
    first = client.post("/api/v1/security/events/ingest", headers={"x-api-key": "local-owner-key"}, json=dup_payload)
    second = client.post("/api/v1/security/events/ingest", headers={"x-api-key": "local-owner-key"}, json=dup_payload)
    assert first.status_code == 200 and second.status_code == 200
    assert second.json().get("deduped") is True

    future = client.post(
        "/api/v1/security/events/ingest",
        headers={"x-api-key": "local-owner-key"},
        json={
            "vendor": "siem",
            "event": {
                "event_id": "late-2",
                "trace_id": trace_2,
                "tenant_id": tenant_id,
                "event_time": "2027-01-01T00:00:00Z",
                "severity": "low",
                "confidence": 0.2,
                "type": "other",
            },
        },
    )
    assert future.status_code == 200, future.text


def test_security_event_replay_deterministic():
    client = TestClient(create_app())
    run = uuid.uuid4().hex[:10]
    r = client.post(
        "/api/v1/security/events/ingest",
        headers={"x-api-key": "local-owner-key"},
        json={
            "vendor": "crowdstrike",
            "event": {
                "detection_id": f"det-replay-{run}-1",
                "tenant_id": f"tenant-r-{run}",
                "trace_id": f"trace-replay-{run}-1",
                "severity": "critical",
                "confidence": 0.99,
                "event_type": "prompt-injection",
            },
        },
    )
    assert r.status_code == 200, r.text
    event_id = str((r.json() or {}).get("id") or "")
    rr = client.get(f"/api/v1/security/events/replay/{event_id}", headers={"x-api-key": "local-owner-key"})
    assert rr.status_code == 200, rr.text
    replay = rr.json()
    assert replay.get("deterministic_match") is True
    assert (replay.get("stored_policy") or {}).get("action") == (replay.get("recomputed_policy") or {}).get("action")


def test_security_event_ingest_load_and_dashboard_latency():
    client = TestClient(create_app())
    run = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-load-{run}"
    start = time.perf_counter()
    for i in range(150):
        res = client.post(
            "/api/v1/security/events/ingest",
            headers={"x-api-key": "local-owner-key"},
            json={
                "vendor": "siem",
                "event": {
                    "event_id": f"load-{run}-{i}",
                    "tenant_id": tenant_id,
                    "trace_id": f"trace-load-{run}-{i % 15}",
                    "event_type": "network" if i % 2 == 0 else "phish",
                    "severity": "medium" if i % 3 else "high",
                    "confidence": 0.52 if i % 5 else 0.82,
                    "event_time": "2026-02-26T10:00:00Z",
                },
            },
        )
        assert res.status_code == 200, res.text
    ingest_elapsed = time.perf_counter() - start
    # Allow runtime variance across local/CI machines while still enforcing
    # a meaningful upper bound for ingest throughput.
    budget_sec = float(os.getenv("SECURITY_EVENT_INGEST_LOAD_BUDGET_SEC", "45.0") or 45.0)
    assert ingest_elapsed < budget_sec

    trend = client.get(
        "/api/v1/admin/bi/security-events/trend-pack?start=2026-02-01&end=2026-03-01",
        headers={"x-api-key": "local-owner-key"},
    )
    assert trend.status_code == 200, trend.text
    body = trend.json()
    assert isinstance(body.get("security_incursions_matrix"), list)
    assert float(body.get("dashboard_query_latency_ms") or 0.0) < 5000.0
