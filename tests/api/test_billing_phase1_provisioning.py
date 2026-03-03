from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_platform_regions_readiness_and_tenant_provision(monkeypatch, tmp_path):
    regions_file = tmp_path / "regions.json"
    regions_file.write_text(
        json.dumps(
            {
                "primary_region": "us-east-1",
                "regions": [
                    {"id": "us-east-1", "role": "primary", "active": True},
                    {"id": "us-west-2", "role": "replica", "active": True},
                ],
                "data_residency_mode": "regional",
                "replication_mode": "async",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLATFORM_REGIONS_PATH", str(regions_file))
    client = TestClient(create_app())

    r0 = client.get("/api/v1/admin/platform/regions/readiness", headers={"x-api-key": "local-owner-key"})
    assert r0.status_code == 200, r0.text
    assert r0.json().get("multi_region_ready") is True

    r1 = client.get("/api/v1/billing/admin/plans", headers={"x-api-key": "local-owner-key"})
    assert r1.status_code == 200, r1.text
    assert isinstance((r1.json() or {}).get("plans"), list)

    r2 = client.post(
        "/api/v1/billing/admin/tenants/provision",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "tenant-1", "plan_id": "growth", "home_region": "us-east-1", "limits": {"recommend_requests_daily": 10000}},
    )
    assert r2.status_code == 200, r2.text
    out = r2.json()
    assert out.get("status") == "provisioned"
    assert out.get("home_region") == "us-east-1"


def test_tenant_provision_rejects_unknown_region(monkeypatch, tmp_path):
    regions_file = tmp_path / "regions_single.json"
    regions_file.write_text(
        json.dumps(
            {
                "primary_region": "us-east-1",
                "regions": [{"id": "us-east-1", "role": "primary", "active": True}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLATFORM_REGIONS_PATH", str(regions_file))
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/billing/admin/tenants/provision",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "tenant-2", "plan_id": "starter", "home_region": "eu-west-1"},
    )
    assert r.status_code == 400
    assert (r.json() or {}).get("detail") == "home_region_not_allowed_by_topology"

