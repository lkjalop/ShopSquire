from src.app.services.procurement_advice import (
    append_sourcing_continuity,
    sourcing_continuity,
    supplier_status_projection,
)
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.procurement import build_procurement_advice


def test_sourcing_continuity_is_bounded_and_quantity_aware():
    prior = {"lines": [{"item_ref": "SKU-A", "quantity": 15},
                       {"item_ref": "SKU-B", "quantity": 5}]}
    continuity = sourcing_continuity(prior)
    assert continuity["units"] == 20
    assert continuity["confirmed"] is False
    assert "15x SKU-A" in append_sourcing_continuity("user: change it", prior)


def test_v2_procurement_advice_has_no_execution_authority():
    envelope = TurnEnvelope.from_suggest_params(
        query="make that 15", uid="u", tenant_id="tenant-a",
        session={"last_sourcing_intent": {"lines": [{"item_ref": "SKU-A", "quantity": 25}]}},
    )
    advice = build_procurement_advice(envelope)
    assert advice["execution_authority"] == "fulfillment_cases"
    assert advice["external_send_gate"] == "human_approval"
    assert advice["continuity"]["units"] == 25


def test_supplier_status_never_promotes_rfq_demand_to_confirmed_availability():
    status = supplier_status_projection(
        {
            "rfq_ref": "RFQ-7",
            "lines": [{"item_ref": "SKU-A", "quantity": 25}],
        },
        tenant_id="tenant-a",
    )
    assert status["status"] == "awaiting_supplier_response"
    assert status["availability_confirmed"] is False
    assert status["action_executed"] is False
    assert status["requested_lines"] == [{"item_ref": "SKU-A", "quantity": 25}]


def test_supplier_status_requires_observed_reply_and_explicit_arrival_evidence():
    status = supplier_status_projection(
        {
            "rfq_ref": "RFQ-8",
            "supplier_reply": {"observed_at": "2026-08-08T08:00:00Z", "status": "received"},
            "supplier_confirmed_arrival": {
                "quantity": 10,
                "arrival_at": "2026-08-11T09:00:00+10:00",
                "source_record_id": "QUOTE-8",
            },
        },
        tenant_id="tenant-a",
    )
    assert status["status"] == "reply_observed"
    assert status["availability_confirmed"] is True
    assert status["supplier_confirmed_arrival"]["source_record_id"] == "QUOTE-8"
