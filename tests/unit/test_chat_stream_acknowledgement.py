from src.app.routers.chat_stream import _typed_acknowledgement


def test_acknowledgement_preserves_confirmed_sku_without_claiming_mutation():
    outcome = _typed_acknowledgement(
        {"query": "increase it to 80", "confirmed_slots": {"canonical_sku": "RGAM-0007"}},
        trace_id="trace-1",
    )

    assert "RGAM-0007" in outcome["message"]
    assert outcome["authority"] == "acknowledgement_only"
    assert outcome["state_changed"] is False
    assert outcome["trace_id"] == "trace-1"


def test_acknowledgement_does_not_invent_product_identity():
    outcome = _typed_acknowledgement({"query": "show status"}, trace_id="trace-2")

    assert "current case" in outcome["message"].lower()
    assert "SKU" not in outcome["message"]


def test_acknowledgement_uses_persisted_exact_product_slot():
    outcome = _typed_acknowledgement(
        {"query": "ship to Sydney", "confirmed_slots": {"exact_product_sku": "RGAM-0007"}},
        trace_id="trace-3",
    )

    assert "Keeping RGAM-0007" in outcome["message"]
    assert outcome["state_changed"] is False
