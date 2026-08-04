from src.app.services.conversation_semantic_proposal import (
    propose_dialogue_act,
    validate_semantic_proposal,
)


STATE = {
    "case_id": "case-80",
    "session_epoch": "epoch-2",
    "product_sku": "RGAM-0007",
    "order_line_id": "line-1",
}


def _proposal(**overrides):
    value = {
        "dialogue_act": "amend_quantity",
        "case_id": "case-80",
        "session_epoch": "epoch-2",
        "references": [
            {"kind": "case", "identifier": "case-80"},
            {"kind": "product", "identifier": "RGAM-0007"},
        ],
        "slot": "quantity",
        "value": 80,
        "confidence": 0.94,
        "rationale": "The pronoun resolves to the only anchored line.",
    }
    value.update(overrides)
    return value


def test_consistent_proposal_is_accepted_but_not_applied() -> None:
    result = validate_semantic_proposal(_proposal(), current_state=STATE)
    assert result.outcome == "accepted"
    assert result.proposal["value"] == 80
    assert STATE["product_sku"] == "RGAM-0007"


def test_cross_case_epoch_and_unknown_reference_fail_closed() -> None:
    assert validate_semantic_proposal(
        _proposal(case_id="case-other"), current_state=STATE
    ).reason == "proposal_case_conflict"
    assert validate_semantic_proposal(
        _proposal(session_epoch="epoch-old"), current_state=STATE
    ).reason == "proposal_epoch_conflict"
    assert validate_semantic_proposal(
        _proposal(references=[{"kind": "product", "identifier": "OTHER-SKU"}]),
        current_state=STATE,
    ).reason == "unknown_product_reference"


def test_missing_value_or_low_confidence_requests_clarification() -> None:
    assert validate_semantic_proposal(
        _proposal(value=None), current_state=STATE
    ).outcome == "clarify"
    assert validate_semantic_proposal(
        _proposal(confidence=0.4), current_state=STATE
    ).outcome == "clarify"


def test_model_failure_degrades_to_typed_clarification() -> None:
    def broken(_input):
        raise TimeoutError("model deadline")

    result = propose_dialogue_act(current_state=STATE, model_proposer=broken)
    assert result.as_dict() == {
        "outcome": "clarify",
        "reason": "semantic_proposer_unavailable",
        "proposal": None,
    }
