from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import get_db
from src.app.models.orm import Base, Product
from src.app.routers.shopping_cases import router
from src.app.services.buyer_requirement_evidence import extract_buyer_requirement_claims


def _client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    app.state.test_engine = engine

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    return TestClient(app)


def test_acceptance_is_case_scoped_versioned_idempotent_and_never_mutates_cart():
    client = _client()
    claims = extract_buyer_requirement_claims(
        "RAM 32GB minimum, 64GB recommended. Storage 1TB NVMe. Windows 11 Pro recommended.",
        source_reference="screenshot-55",
    )
    created = client.post(
        "/api/v1/shopping-cases/case-ot/requirement-proposals",
        headers={"X-Tenant-Id": "tenant-a"},
        json={
            "uid": "buyer-1", "retained_purpose": "OT cyber range",
            "source_reference": "screenshot-55",
            "claims": [claim.model_dump(mode="json") for claim in claims],
        },
    )
    assert created.status_code == 201
    proposal = created.json()
    selected = [claim["claim_id"] for claim in proposal["claims"]]
    body = {
        "uid": "buyer-1", "expected_proposal_version": 1,
        "accepted_claim_ids": selected, "rejected_claim_ids": [],
        "corrections": [{
            "claim_id": selected[0], "attribute": "ram_gb", "operator": ">=",
            "value": 48, "unit": "GB", "requirement_class": "minimum",
            "constraint_tier": "preferred",
        }],
        "research_choice": "research_and_corroborate",
    }
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "accept-case-ot-1"}
    accepted = client.post(
        f"/api/v1/shopping-cases/case-ot/requirement-proposals/{proposal['proposal_id']}/accept",
        headers=headers, json=body,
    )
    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["status"] == "accepted_provisional"
    assert payload["accepted_claims"][0]["value"] == 48
    assert payload["accepted_claims"][0]["buyer_corrected"] is True
    assert payload["research_authorized"] is True
    assert payload["qualification_authority"] == "none"
    assert payload["cart_mutation"] == "not_authorized"
    assert payload["provider_accounting"] == {"external_calls": 0, "paid_calls": 0}
    assert payload["evidence_acquisition"]["selected_stage"] == "buyer_upload"
    assert payload["evidence_acquisition"]["paid_calls"] == 0

    replay = client.post(
        f"/api/v1/shopping-cases/case-ot/requirement-proposals/{proposal['proposal_id']}/accept",
        headers=headers, json=body,
    )
    assert replay.status_code == 200
    assert replay.json() == payload


def test_acceptance_rejects_cross_buyer_and_stale_versions():
    client = _client()
    claim = extract_buyer_requirement_claims(
        "RAM 32GB minimum", source_reference="buyer-paste",
    )[0]
    proposal = client.post(
        "/api/v1/shopping-cases/case-1/requirement-proposals",
        json={"uid": "buyer-1", "source_reference": "buyer-paste", "claims": [claim.model_dump(mode="json")]},
    ).json()
    url = f"/api/v1/shopping-cases/case-1/requirement-proposals/{proposal['proposal_id']}/accept"
    body = {
        "uid": "buyer-2", "expected_proposal_version": 1,
        "accepted_claim_ids": [claim.claim_id], "rejected_claim_ids": [],
        "corrections": [], "research_choice": "local_only",
    }
    assert client.post(url, headers={"Idempotency-Key": "cross-buyer-1"}, json=body).status_code == 403

    body["uid"] = "buyer-1"
    body["expected_proposal_version"] = 99
    response = client.post(url, headers={"Idempotency-Key": "stale-version-1"}, json=body)
    assert response.status_code == 409


def test_fulfillment_options_are_proposals_not_cart_or_supplier_actions():
    client = _client()
    claim = extract_buyer_requirement_claims("RAM 32GB minimum", source_reference="upload")[0]
    client.post(
        "/api/v1/shopping-cases/case-bulk/requirement-proposals",
        json={"uid": "buyer-1", "source_reference": "upload", "claims": [claim.model_dump(mode="json")]},
    )
    response = client.post("/api/v1/shopping-cases/case-bulk/fulfillment-options", json={
        "uid": "buyer-1", "requested_quantity": 30, "available_now": 12,
        "known_lead_time_days": 8, "deadline_days": 10,
        "has_next_best": True, "has_architecture_alternative": True,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["cart_mutation"] == "not_authorized"
    assert payload["supplier_send"] == "not_authorized"
    assert [row["choice_id"] for row in payload["choices"]][:3] == [
        "split_delivery", "wait_preferred", "next_best_now",
    ]


def test_live_research_is_case_scoped_and_never_authorizes_commerce(monkeypatch):
    client = _client()
    monkeypatch.setenv(
        "EXTERNAL_RESEARCH_SEARCH_URL",
        "http://127.0.0.1:8888/search?q={query}&format=json",
    )

    def fixture_research(purpose, *, search_url_template, workload):
        assert purpose == "OT cyber range"
        assert "{query}" in search_url_template
        assert workload == "ot_cyber_range"
        return {
            "schema_version": "official-workload-research-v1",
            "run_id": "fixture-run", "purpose": purpose, "workload": workload,
            "claims": [{
                "claim_id": "official-os", "attribute": "operating_system",
                "operator": "one_of", "value": ["Windows 11 Pro"],
                "unit": None, "requirement_class": "minimum",
                "claim_class": "attested", "authority_status": "verified_official",
                "freshness_status": "fresh", "source_id": "microsoft_learn_hyperv",
                "acceptance_status": "accepted_official",
            }],
            "context_claims": [], "unresolved": [], "receipts": [],
            "provider_accounting": {"external_calls": 2, "paid_calls": 0},
            "execution_mode": "deterministic_fixture", "authority_rule": "official only",
        }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_workload",
        fixture_research,
    )
    response = client.post("/api/v1/shopping-cases/sc-trace-1/research", json={
        "uid": "buyer-1", "retained_purpose": "OT cyber range",
        "workload": "ot_cyber_range",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "sc-trace-1"
    assert payload["trace_id"] == "trace-1"
    assert payload["status"] == "research_completed"
    assert payload["research"]["claims"][0]["authority_status"] == "verified_official"
    assert payload["cart_mutation"] == "not_authorized"
    assert payload["supplier_send"] == "not_authorized"

    with Session(client.app.state.test_engine) as db:
        db.add(Product(
            sku="WS-EXACT-1", name="Exact mobile workstation",
            price_cents=500_000, currency="AUD", active=True,
        ))
        db.commit()
    proposal = client.post("/api/v1/shopping-cases/sc-trace-1/cart-proposals", json={
        "uid": "buyer-1", "sku": "WS-EXACT-1", "quantity": 30,
    })
    assert proposal.status_code == 200
    planned = proposal.json()
    assert planned["status"] == "confirmation_required"
    assert planned["risk"] == "confirm"
    assert planned["cart_mutation"] == "not_applied"
    assert planned["supplier_send"] == "not_authorized"
    assert planned["ops"][0]["allow_sourcing"] is True
