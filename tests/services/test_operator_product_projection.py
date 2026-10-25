from types import SimpleNamespace
import uuid

import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services import market_projection
from src.app.services.operator_tenant_membership import grant_membership, principal_hash_for_api_key, revoke_membership


@pytest.fixture
def operator_client(monkeypatch):
    from fastapi.testclient import TestClient
    from src.app.main import create_app

    key = f"projection-test-owner-{uuid.uuid4().hex}"
    tenant = f"projection-test-{uuid.uuid4().hex}"
    principal = principal_hash_for_api_key(key)
    monkeypatch.setenv("OWNER_API_KEY", key)
    monkeypatch.setenv("OPERATOR_TENANT_MEMBERSHIP_MODE", "strict")
    app = create_app()
    with Session(app.state.engine) as db:
        grant_membership(db, principal_hash=principal, tenant_id=tenant, role="owner",
                         auth_method="api_key", created_by="owned-test-fixture")
        db.commit()
    client = TestClient(app)
    try:
        yield client, {"x-api-key": key, "x-tenant-id": tenant}, principal
    finally:
        client.close()
        with Session(app.state.engine) as db:
            db.execute(text("DELETE FROM operator_tenant_membership WHERE principal_hash=:principal"),
                       {"principal": principal})
            db.commit()


def test_sparse_projection_sources_do_not_poison_the_caller_transaction():
    db = Session(create_engine("sqlite+pysqlite:///:memory:", future=True))
    try:
        result = market_projection.load_projection_inputs(db, tenant_id="tenant-a")

        assert result["sales_status"] == "insufficient_data"
        assert result["inventory_status"] == "unavailable"
        assert db.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        db.close()


def test_operator_projection_keeps_demo_wholesale_unapproved(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.catalog_read_model.get_variant",
        lambda *a, **k: SimpleNamespace(price_cents=200_000, currency="AUD"))
    monkeypatch.setattr(
        "src.app.services.supplier_catalog.best_supplier_cost",
        lambda *a, **k: {
            "unit_cost_cents": 150_000, "cost_basis": "seeded_wholesale_estimate",
            "simulation_only": True,
        })
    monkeypatch.setattr(
        market_projection, "projections",
        lambda *a, **k: {"SKU-1": {"units_per_day": 2.0}})
    out = market_projection.operator_product_projection(
        object(), sku="SKU-1", tenant_id="tenant-a")
    assert out["gross_margin_pct"] == 0.25
    assert out["projected_profit_30d_cents"] == 3_000_000
    assert out["discount_headroom_cents"] is None
    assert out["discount_authorized"] is False
    assert out["simulation_only"] is True


def test_product_projection_endpoint_requires_operator_auth():
    from fastapi.testclient import TestClient
    from src.app.main import create_app

    response = TestClient(create_app()).get(
        "/api/v1/admin/bi/product-projection", params={"sku": "SKU-1"})
    assert response.status_code in {401, 403}


def test_commercial_proposal_submission_queues_review_without_execution(monkeypatch, operator_client):
    client, headers, _ = operator_client

    monkeypatch.setattr(
        market_projection,
        "operator_product_projection",
        lambda *a, **k: {
            "available": True,
            "action_proposals": {
                "discount": {
                    "eligible": True,
                    "reasons": [],
                    "human_gate": "required",
                    "auto_applied": False,
                }
            },
        },
    )
    monkeypatch.setattr(
        "src.app.routers.approvals.enqueue_approval",
        lambda *a, **k: "approval-1",
    )
    response = client.post(
        "/api/v1/admin/bi/product-projection/SKU-1/proposals/discount",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "queued": True,
        "approval_id": "approval-1",
        "action_type": "discount",
        "human_gate": "required",
        "executed": False,
    }


def test_commercial_proposal_submission_fails_closed(monkeypatch, operator_client):
    client, headers, _ = operator_client

    monkeypatch.setattr(
        market_projection,
        "operator_product_projection",
        lambda *a, **k: {
            "available": True,
            "action_proposals": {
                "replenishment": {
                    "authorized": False,
                    "reasons": ["untrusted_or_stale_atp"],
                }
            },
        },
    )
    response = client.post(
        "/api/v1/admin/bi/product-projection/SKU-1/proposals/replenishment",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reasons"] == ["untrusted_or_stale_atp"]


def test_newsletter_endpoint_returns_human_gated_draft(monkeypatch, operator_client):
    client, headers, _ = operator_client

    monkeypatch.setattr(
        market_projection,
        "operator_product_projection",
        lambda *a, **k: {
            "available": True,
            "sku": k["sku"],
            "name": "Qualified Product",
            "projection": {"dead_stock": True, "dsi_days": 120},
            "action_proposals": {
                "discount": {
                    "eligible": True,
                    "recommended_discount_pct": 0.05,
                }
            },
        },
    )
    response = client.post(
        "/api/v1/admin/bi/newsletter-draft",
        headers=headers,
        json={"skus": ["SKU-1"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["featured_skus"] == ["SKU-1"]
    assert body["status"] == "draft"
    assert body["send_gate"] == "human"
    assert body["sent"] is False


def test_operator_projection_rejects_a_tenant_without_membership(operator_client):
    client, headers, _ = operator_client
    response = client.get("/api/v1/admin/bi/product-projection", params={"sku": "SKU-1"},
                          headers={**headers, "x-tenant-id": "ungranted-test-tenant"})
    assert response.status_code == 403
    assert response.json()["detail"] == "operator_tenant_membership_required"


def test_operator_projection_rejects_revoked_membership(operator_client):
    client, headers, principal = operator_client
    with Session(client.app.state.engine) as db:
        assert revoke_membership(db, principal_hash=principal, tenant_id=headers["x-tenant-id"])
        db.commit()
    response = client.get("/api/v1/admin/bi/product-projection", params={"sku": "SKU-1"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "operator_tenant_membership_required"
