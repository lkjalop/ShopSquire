import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text as sql_text

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.decision_log import log_trace_event


def _headers() -> dict:
    return {"x-api-key": "local-merchant-key"}


def test_cv_analyze_emits_security_scan_contract(monkeypatch, tmp_path):
    db_file = tmp_path / "trace_contract_cv.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("CV_ASYNC_QUEUE_ENABLED", "0")
    monkeypatch.setenv("INCIDENT_MATRIX_GATE_ENABLED", "1")

    app = create_app()
    client = TestClient(app)

    case_id = f"cv-contract-{uuid.uuid4().hex[:10]}"
    resp = client.post(
        "/api/v1/cv/analyze",
        headers=_headers(),
        json={
            "case_id": case_id,
            "labels": ["catalog", "laptop"],
            "extracted_text": "MacBook Pro 14-inch catalogue page. No payment change requested.",
            "description": "benign supplier catalogue",
        },
    )
    assert resp.status_code == 200, resp.text

    q = client.get(f"/api/v1/decisions/{case_id}/query?include_events=true", headers=_headers())
    assert q.status_code == 200, q.text
    body = q.json()
    events = body.get("events") or []
    sec_events = [e for e in events if str(e.get("event_type")) == "security_scan"]
    assert sec_events, body

    payload = sec_events[-1].get("payload") or {}
    contract = payload.get("_trace_contract") or {}
    security = payload.get("security") or payload.get("details") or {}
    assert contract.get("name") == "security_scan.v1"
    assert bool(contract.get("matrix_complete")) is True
    assert security.get("route") in {"allow", "review", "escalate", "block"}
    assert isinstance(security.get("signals"), dict)
    assert "threshold_version" in security
    assert isinstance((security.get("bitemporal") or {}), dict)


def test_incident_close_requires_matrix_complete(monkeypatch, tmp_path):
    db_file = tmp_path / "matrix_gate.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("INCIDENT_MATRIX_GATE_ENABLED", "1")

    app = create_app()
    client = TestClient(app)

    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    incident_id = str(uuid.uuid4())

    with db_session() as db:
        db.execute(
            sql_text(
                "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status) "
                "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status)"
            ),
            {
                "id": incident_id,
                "event_id": trace_id,
                "created_by": "buyer",
                "severity": "warn",
                "title": "Matrix gate regression",
                "description": json.dumps({"trace_id": trace_id}),
                "status": "open",
            },
        )
        # Legacy/incomplete payload: missing route/threshold_version/bitemporal.
        db.execute(
            sql_text(
                "INSERT INTO decision_trace_events (id, trace_id, event_type, source_type, source_id, payload, created_at) "
                "VALUES (:id, :trace_id, 'security_scan', 'agent', 'legacy_test', :payload, :created_at)"
            ),
            {
                "id": f"legacy-{uuid.uuid4().hex[:10]}",
                "trace_id": trace_id,
                "payload": json.dumps({"details": {"qr_code_detected": True}, "severity": "warn"}),
                "created_at": "2020-01-01T00:00:00",
            },
        )
        db.commit()

    blocked = client.post(f"/api/v1/admin/incidents/{incident_id}/status?status=resolved", headers=_headers())
    assert blocked.status_code == 409, blocked.text

    log_trace_event(
        trace_id=trace_id,
        event_type="security_scan",
        source_type="agent",
        source_id="Security_Observer_Agent",
        target_type="complaint",
        target_id=trace_id,
        payload={
            "severity": "warn",
            "route": "review",
            "threshold_version": "security-v1",
            "details": {"signals": {"qr_code_detected": True}},
        },
    )

    ok = client.post(f"/api/v1/admin/incidents/{incident_id}/status?status=resolved", headers=_headers())
    assert ok.status_code == 200, ok.text
    assert (ok.json() or {}).get("updated") is True


def test_cv_analyze_quota_blocks_flood(monkeypatch, tmp_path):
    db_file = tmp_path / "quota_gate.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("CV_ASYNC_QUEUE_ENABLED", "0")
    monkeypatch.setenv("TENANT_QUOTAS_ENABLED", "1")
    monkeypatch.setenv("TENANT_QUOTA_CV_CALLS_DAILY", "1")

    class FakeRedis:
        def __init__(self):
            self._store = {}

        def get(self, key):
            return self._store.get(key)

        def incrby(self, key, amount):
            self._store[key] = int(self._store.get(key, 0) or 0) + int(amount)
            return self._store[key]

        def expire(self, *_args, **_kwargs):
            return True

    from src.app.routers import cv as cv_router

    fake = FakeRedis()
    monkeypatch.setattr(cv_router, "get_redis", lambda: fake)

    app = create_app()
    client = TestClient(app)
    payload = {"case_id": "tenant-flood-1", "labels": ["catalog"], "extracted_text": "benign"}

    first = client.post("/api/v1/cv/analyze", headers=_headers(), json=payload)
    assert first.status_code == 200, first.text

    second = client.post("/api/v1/cv/analyze", headers=_headers(), json=payload)
    assert second.status_code == 429, second.text
    detail = second.json().get("detail") or {}
    assert detail.get("error") == "tenant_quota_exceeded"

