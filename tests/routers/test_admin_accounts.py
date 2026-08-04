from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.app.models.db import set_engine
from src.app.routers.admin_accounts import router
from src.app.services.account_intelligence import resolve_exact_external_identity


def _apply(engine, filename: str) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original = module.op
        module.op = operations
        try:
            module.upgrade()
        finally:
            module.op = original


def test_admin_account_api_is_tenant_scoped_and_proposal_only(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'accounts-api.sqlite'}", future=True)
    for migration in (
        "20260810_account_intelligence.py",
        "20260814_conversation_fact_observations.py",
        "20260819_party_timeline.py",
        "20260822_party_redirect_execution.py",
    ):
        _apply(engine, migration)
    set_engine(engine)
    left = resolve_exact_external_identity(
        tenant_id="default", source="csv", object_type="customer",
        external_id="left", party_type="buyer_account", display_name="Left Account",
    )["party_id"]
    right = resolve_exact_external_identity(
        tenant_id="default", source="csv", object_type="customer",
        external_id="right", party_type="buyer_account", display_name="Right Account",
    )["party_id"]

    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ABAC_ENABLED", "0")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, headers={"x-api-key": "local-owner-key"})

    listed = client.get("/api/v1/admin/accounts")
    assert listed.status_code == 200
    assert {item["party_id"] for item in listed.json()["accounts"]} == {left, right}

    created = client.post(
        "/api/v1/admin/accounts/identity/proposals",
        json={
            "proposal_type": "merge",
            "left_party_id": left,
            "right_party_id": right,
            "reason": "Same business identifier; needs human review.",
        },
    )
    assert created.status_code == 200
    assert created.json()["authority"] == "proposal_only"
    assert created.json()["execution_allowed"] is False

    resolved = client.post(
        f"/api/v1/admin/accounts/identity/proposals/{created.json()['id']}/resolve",
        json={"resolution": "approved", "note": "Reviewed; separate execution required."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["execution_allowed"] is False
    assert resolved.json()["manual_execution_required"] is True

    timeline = client.get(f"/api/v1/admin/accounts/{left}/timeline")
    assert timeline.status_code == 200
    identity_event = next(
        event for event in timeline.json()["timeline"]
        if event["event_class"] == "identity_resolution"
    )
    assert identity_event["status"] == "approved"
    assert identity_event["execution_allowed"] is False


def test_owner_previews_and_executes_approved_redirect_without_moving_history(
    tmp_path, monkeypatch
):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'accounts-execute.sqlite'}",
        future=True,
    )
    for migration in (
        "20260810_account_intelligence.py",
        "20260819_party_timeline.py",
        "20260822_party_redirect_execution.py",
    ):
        _apply(engine, migration)
    set_engine(engine)
    left = resolve_exact_external_identity(
        tenant_id="default", source="csv", object_type="customer",
        external_id="left-execute", party_type="buyer_account",
    )["party_id"]
    right = resolve_exact_external_identity(
        tenant_id="default", source="csv", object_type="customer",
        external_id="right-execute", party_type="buyer_account",
    )["party_id"]
    from src.app.services.account_intelligence import (
        propose_party_merge,
        resolve_identity_resolution_proposal,
    )
    proposal = propose_party_merge(
        tenant_id="default", left_party_id=left, right_party_id=right,
        evidence={}, proposed_by="proposal-creator",
    )
    resolve_identity_resolution_proposal(
        tenant_id="default", proposal_id=proposal["id"],
        resolution="approved", resolved_by="independent-reviewer",
        note="Independent evidence review passed.",
    )
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ABAC_ENABLED", "0")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, headers={"x-api-key": "local-owner-key"})

    impact = client.get(
        f"/api/v1/admin/accounts/identity/proposals/{proposal['id']}/impact"
    )
    assert impact.status_code == 200
    assert impact.json()["executable"] is True
    executed = client.post(
        f"/api/v1/admin/accounts/identity/proposals/{proposal['id']}/execute",
        json={
            "expected_version": impact.json()["graph_version"],
            "idempotency_key": "router-merge-execution",
            "note": "Execute reviewed canonical redirect.",
        },
    )
    assert executed.status_code == 200
    assert executed.json()["historical_records_moved"] is False
    canonical = client.get(
        f"/api/v1/admin/accounts/identity/canonical/{left}"
    )
    assert canonical.status_code == 200
    assert canonical.json()["canonical_party_id"] == right
