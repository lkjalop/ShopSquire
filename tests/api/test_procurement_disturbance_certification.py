from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.app.main import app
from src.app.services.procurement_case_state import DestinationAllocation, ProcurementCaseState
from src.app.services.procurement_disturbance import ProcurementDisturbance
from src.app.services.procurement_scenario_harness import ProcurementScenario


OWNER_HEADERS = {"x-api-key": "local-owner-key"}


def _request() -> dict:
    now = datetime(2026, 8, 17, tzinfo=timezone.utc)
    state = ProcurementCaseState(
        case_id="cert-case", revision=3, objective="topology neutral fleet",
        requested_quantity=30,
        destinations=[DestinationAllocation(
            location_ref="destination-token", location_kind="address_token", quantity=30,
        )],
    )
    scenario = ProcurementScenario(
        scenario_id="live-api-matrix", state=state,
        disturbances=tuple(
            ProcurementDisturbance(
                disturbance_id=f"event-{kind}", kind=kind,
                case_id=state.case_id, expected_case_revision=state.revision,
                known_at=now.isoformat(), effective_at=now.isoformat(),
                evidence_ref=f"certification:{kind}",
            )
            for kind in (
                "supplier_delay", "stock_correction", "price_change",
                "buyer_quantity_change", "quote_expiry", "supplier_rejection",
                "supplier_substitute",
            )
        ),
    )
    return {
        "scenario": scenario.model_dump(mode="json"),
        "knowledge_cutoff": now.isoformat(),
        "evaluation_time": now.isoformat(),
    }


def test_disturbance_certificate_is_sealed_and_side_effect_free(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_CERTIFICATION_ENABLED", "1")
    response = TestClient(app, headers=OWNER_HEADERS).post(
        "/api/v1/certification/procurement/disturbances/evaluate", json=_request(),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["result"]["passed"] is True
    assert len(payload["result"]["projections"]) == 7
    assert payload["provider_accounting"] == {
        "external_calls": 0, "rfq_calls": 0, "cart_mutations": 0, "paid_calls": 0,
    }
    assert payload["commercial_authority_granted"] is False
    assert len(payload["artifact_sha256"]) == 64


def test_disturbance_certificate_is_hidden_when_disabled(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_CERTIFICATION_ENABLED", raising=False)
    response = TestClient(app, headers=OWNER_HEADERS).post(
        "/api/v1/certification/procurement/disturbances/evaluate", json=_request(),
    )
    assert response.status_code == 404


def test_conversational_spatiotemporal_certificate_is_live_api_sealed(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_CERTIFICATION_ENABLED", "1")
    response = TestClient(app, headers=OWNER_HEADERS).post(
        "/api/v1/certification/procurement/conversational-spatiotemporal/evaluate",
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["passed"] is True
    assert payload["invariants"]["destination_move_applied"] is True
    assert payload["invariants"]["workload_query_excludes_destinations"] is True
    assert payload["invariants"]["zero_calls_before_authorization"] is True
    assert payload["invariants"]["no_cart_mutation"] is True
    assert payload["canonical_truth"]["commerce_authority"] == "NONE"
    assert len(payload["artifact_sha256"]) == 64
