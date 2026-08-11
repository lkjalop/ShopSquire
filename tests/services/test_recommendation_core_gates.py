from src.app.services.recommendation_core.gates import (
    ClarificationObligationState,
    slot_gap_clarify,
)


def test_known_use_case_does_not_get_asked_again_without_hardware_requirements():
    assert slot_gap_clarify(
        has_products=True,
        budget_known=True,
        has_requirements=False,
        has_use_case=True,
    ) is None


def test_missing_use_case_and_requirements_still_clarifies():
    question = slot_gap_clarify(
        has_products=True,
        budget_known=True,
        has_requirements=False,
        has_use_case=False,
    )
    assert question and question["id"] == "ask_use_case"


def test_explicit_explanation_obligation_defers_budget_question():
    assert slot_gap_clarify(
        has_products=True,
        budget_known=False,
        has_requirements=True,
        has_use_case=False,
        allow_budget_question=False,
    ) is None


def test_empty_retrieval_missing_budget_recovers_with_clarify():
    # The inversion fix: zero results + a missing slot is when clarify matters MOST.
    q = slot_gap_clarify(has_products=False, budget_known=False, has_requirements=False)
    assert q and q["reason"] == "empty_budget_slot"


def test_empty_retrieval_missing_use_case_recovers_with_clarify():
    q = slot_gap_clarify(
        has_products=False, budget_known=True, has_requirements=False, has_use_case=False
    )
    assert q and q["reason"] == "empty_use_case_slot"


def test_empty_retrieval_fully_specified_stays_honest_no_match():
    # Budget + requirements known but still empty -> not a slot gap; keep the honest no-match.
    assert slot_gap_clarify(
        has_products=False, budget_known=True, has_requirements=True
    ) is None


def test_empty_retrieval_never_contradicts_an_existing_selection():
    assert slot_gap_clarify(
        has_products=False,
        has_selection=True,
        budget_known=False,
        has_requirements=False,
    ) is None


def test_empty_turn_never_claims_no_match_while_a_shortlist_is_visible():
    assert slot_gap_clarify(
        has_products=False,
        budget_known=False,
        has_requirements=False,
        obligation_state=ClarificationObligationState(has_shortlist=True),
    ) is None


def test_empty_turn_never_claims_no_match_while_cart_context_is_visible():
    assert slot_gap_clarify(
        has_products=False,
        budget_known=False,
        has_requirements=False,
        obligation_state=ClarificationObligationState(has_cart=True),
    ) is None


def test_fit_explanation_obligation_outranks_generic_budget_question():
    assert slot_gap_clarify(
        has_products=True,
        budget_known=False,
        has_requirements=True,
        obligation_state=ClarificationObligationState(
            has_shortlist=True,
            has_fit_explanation_obligation=True,
        ),
    ) is None
