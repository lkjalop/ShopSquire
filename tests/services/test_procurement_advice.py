from src.app.services.procurement_advice import append_sourcing_continuity, sourcing_continuity
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
