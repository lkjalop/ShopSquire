from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_admin_security_storage_policy_crud_and_ingest_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_EVENT_STORAGE_TARGETS", "database")
    monkeypatch.setenv("SECURITY_EVENT_OBJECT_PATH", str(tmp_path / "object"))
    monkeypatch.setenv("SECURITY_EVENT_WAREHOUSE_PATH", str(tmp_path / "warehouse"))
    monkeypatch.setenv("SECURITY_EVENT_LAKEHOUSE_PATH", str(tmp_path / "lakehouse"))
    monkeypatch.setenv("SECURITY_EVENT_BLOCK_PATH", str(tmp_path / "block"))

    client = TestClient(create_app())
    tenant = f"tenant-pol-{uuid.uuid4().hex[:8]}"
    hdr = {"x-api-key": "local-owner-key"}

    _ = client.delete("/api/v1/admin/security/storage-policy", params={"tenant_id": tenant}, headers=hdr)
    r0 = client.get("/api/v1/admin/security/storage-policy", params={"tenant_id": tenant}, headers=hdr)
    assert r0.status_code == 200, r0.text
    assert r0.json().get("source") == "env_default"
    assert r0.json().get("effective_storage_targets") == ["database"]

    put = client.put(
        "/api/v1/admin/security/storage-policy",
        params={"tenant_id": tenant},
        headers=hdr,
        json={"storage_targets": ["object", "warehouse"]},
    )
    assert put.status_code == 200, put.text
    put_body = put.json()
    assert put_body.get("ok") is True
    assert put_body.get("storage_targets") == ["object", "warehouse"]
    assert put_body.get("source") == "tenant_policy"

    ingest_policy = client.post(
        "/api/v1/security/events/ingest",
        headers=hdr,
        json={
            "vendor": "siem",
            "event": {
                "event_id": f"pol-{uuid.uuid4().hex[:8]}",
                "trace_id": f"trace-pol-{uuid.uuid4().hex[:8]}",
                "tenant_id": tenant,
                "event_type": "network",
                "severity": "medium",
                "confidence": 0.55,
            },
        },
    )
    assert ingest_policy.status_code == 200, ingest_policy.text
    body_policy = ingest_policy.json()
    assert body_policy.get("storage_targets") == ["object", "warehouse"]
    res_policy = body_policy.get("storage_results") or {}
    assert res_policy.get("object") is True
    assert res_policy.get("warehouse") is True

    ingest_override = client.post(
        "/api/v1/security/events/ingest",
        headers=hdr,
        json={
            "vendor": "siem",
            "storage_targets": ["database"],
            "event": {
                "event_id": f"ovr-{uuid.uuid4().hex[:8]}",
                "trace_id": f"trace-ovr-{uuid.uuid4().hex[:8]}",
                "tenant_id": tenant,
                "event_type": "network",
                "severity": "medium",
                "confidence": 0.55,
            },
        },
    )
    assert ingest_override.status_code == 200, ingest_override.text
    body_override = ingest_override.json()
    assert body_override.get("storage_targets") == ["database"]
    assert (body_override.get("storage_results") or {}).get("database") is True

    delete = client.delete("/api/v1/admin/security/storage-policy", params={"tenant_id": tenant}, headers=hdr)
    assert delete.status_code == 200, delete.text
    assert delete.json().get("source") == "env_default"
