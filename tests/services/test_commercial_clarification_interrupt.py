from src.app.services.clarification_state import (
    build_pending_clarification,
    commercial_obligations,
    reduce_clarification_turn,
)


def _pending():
    return build_pending_clarification(
        {
            "id": "external_research_consent",
            "text": "May I check approved official sources?",
            "goal": "authorize_bounded_external_research",
        },
        original_query="I need laptops for a factory rollout.",
        trace_id="case-commercial-interrupt",
        now_epoch=1_000,
    )

def test_quantity_deadline_and_selection_interrupt_research_question_without_rewrite():
    query = "I need 40 of the most expensive one within 3 days."
    result = reduce_clarification_turn(
        query=query, nqe_selection={}, pending=_pending(), now_epoch=1_001,
    )

    assert result.relation == "interrupt"
    assert result.suspend_pending is True
    assert result.consume_pending is False
    assert result.effective_query == query
    assert result.interrupting_obligations == (
        "quantity", "deadline", "selected_product",
    )


def test_supplier_enquiry_interrupts_and_does_not_become_research_answer():
    query = "Yes, please raise a supplier enquiry for the shortfall."
    result = reduce_clarification_turn(
        query=query, nqe_selection={}, pending=_pending(), now_epoch=1_001,
    )

    assert result.relation == "interrupt"
    assert result.answer is None
    assert result.effective_query == query
    assert result.interrupting_obligations == ("supplier_enquiry",)


def test_one_turn_can_expose_all_independent_commercial_obligations():
    assert commercial_obligations(
        "Swap to the selected workstation, set quantity to 30 under AUD 6000, "
        "split delivery within 10 days and ask the supplier for the shortfall."
    ) == (
        "quantity", "deadline", "budget", "selected_product",
        "supplier_enquiry", "cart_mutation", "fulfilment_choice",
    )
