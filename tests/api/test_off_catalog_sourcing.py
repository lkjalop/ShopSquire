from contextlib import nullcontext

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models.orm import Base, ShoppingCase
from src.app.routers import fulfillment_cases


def _request() -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/", "headers": [],
        "query_string": b"", "client": ("127.0.0.1", 12345), "scheme": "http",
        "server": ("testserver", 80),
    })


def test_explicit_off_catalog_acceptance_creates_only_internal_draft(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    db.add(ShoppingCase(
        case_id="shop-case-1", tenant_id="default", uid="buyer-1",
        retained_purpose="Buy an ERP licence", revision=3,
    ))
    db.commit()
    monkeypatch.setattr(fulfillment_cases, "db_session", lambda: nullcontext(db))

    body = fulfillment_cases.OffCatalogSourcingBody(
        uid="buyer-1",
        shopping_case_id="shop-case-1",
        expected_case_revision=3,
        trace_id="trace-erp-1",
        subject_label="ERP licence",
        quantity=200,
        commercial_terms={"currency": "AUD", "billing_cadence": "annual"},
        canonical_identity={"title": "Example ERP", "publisher": "Example"},
        accepted_claim_ids=["claim-1", "claim-2"],
        source_urls=["https://example.invalid/requirements"],
        budget_gap_cents=500_000,
        best_catalog_alternative={"sku": "ALT-1", "gap": "licence not stocked"},
    )
    created = fulfillment_cases.confirm_off_catalog_sourcing(body, _request())
    replay = fulfillment_cases.confirm_off_catalog_sourcing(body, _request())

    assert created["state"] == "COMMITTED"
    assert created["supplier_contacted"] is False
    assert created["draft"]["status"] == "internal_sourcing_brief"
    assert created["draft"]["requires_operator_supplier_resolution"] is True
    assert replay["case_id"] == created["case_id"]
    assert replay["idempotent"] is True
    current = fulfillment_cases.fwf.repository.current_version(db, created["case_id"], "default")
    assert current is not None
    assert current.state_json["source_shopping_case"] == {"case_id": "shop-case-1", "revision": 3}
    assert current.state_json["sourcing_brief"]["supplier_contacted"] is False
    assert current.state_json["sourcing_brief"]["canonical_identity"]["title"] == "Example ERP"
    assert current.state_json["sourcing_brief"]["accepted_claim_ids"] == ["claim-1", "claim-2"]
    assert current.state_json["sourcing_brief"]["budget_gap_cents"] == 500_000
    assert current.state_json["sourcing_brief"]["best_catalog_alternative"]["sku"] == "ALT-1"


def test_off_catalog_acceptance_rejects_stale_case_revision(monkeypatch):
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    db.add(ShoppingCase(case_id="shop-case-2", tenant_id="default", uid="buyer-2", revision=4))
    db.commit()
    monkeypatch.setattr(fulfillment_cases, "db_session", lambda: nullcontext(db))

    body = fulfillment_cases.OffCatalogSourcingBody(
        uid="buyer-2", shopping_case_id="shop-case-2", expected_case_revision=3,
        trace_id="trace-stale", subject_label="CRM seats",
    )
    try:
        fulfillment_cases.confirm_off_catalog_sourcing(body, _request())
        assert False, "expected a revision conflict"
    except fulfillment_cases.HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "case_revision_conflict"
