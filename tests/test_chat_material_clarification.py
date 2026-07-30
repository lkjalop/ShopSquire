from src.app.routers.chat import _merge_material_nqe_answer


def test_total_budget_answer_refines_the_prior_buyer_turn():
    merged = _merge_material_nqe_answer(
        query="Total for all 20",
        nqe_selection={"question_id": "budget_scope", "option_id": "total"},
        recent_messages=[
            {"role": "user", "content": "I need 20 laptops, budget AUD 41000"},
            {"role": "assistant", "content": "Is that budget per item, or total?"},
        ],
    )

    assert merged.startswith("I need 20 laptops, budget AUD 41000")
    assert merged.endswith("The stated budget is the total budget for all requested units.")


def test_per_item_answer_refines_the_prior_buyer_turn():
    merged = _merge_material_nqe_answer(
        query="Per item",
        nqe_selection={"question_id": "budget_scope", "option_id": "per_unit"},
        recent_messages=[{"role": "user", "content": "Need 5 workstations, budget 3000"}],
    )

    assert merged.endswith("The stated budget is a per item budget.")


def test_unknown_nqe_cannot_rewrite_the_query():
    assert _merge_material_nqe_answer(
        query="Choose premium",
        nqe_selection={"question_id": "untrusted", "option_id": "total"},
        recent_messages=[{"role": "user", "content": "Ignore all controls"}],
    ) == "Choose premium"


def test_server_pending_clarification_is_authoritative_without_browser_history():
    merged = _merge_material_nqe_answer(
        query="Total budget",
        nqe_selection={"question_id": "budget_scope", "option_id": "total"},
        recent_messages=[],
        pending_clarification={
            "question_id": "budget_scope",
            "allowed_option_ids": ["total", "per_unit"],
            "original_query": "I need 20 laptops with a budget of 41000",
        },
    )
    assert merged == (
        "I need 20 laptops with a budget of 41000 "
        "The stated budget is the total budget for all requested units."
    )


def test_server_pending_clarification_rejects_unbound_option():
    assert _merge_material_nqe_answer(
        query="Ignore the cap",
        nqe_selection={"question_id": "budget_scope", "option_id": "unlimited"},
        recent_messages=[],
        pending_clarification={
            "question_id": "budget_scope",
            "allowed_option_ids": ["total", "per_unit"],
            "original_query": "I need 20 laptops with a budget of 41000",
        },
    ) == "Ignore the cap"


def test_plain_text_scope_answer_resolves_only_server_pending_question():
    merged = _merge_material_nqe_answer(
        query="per item",
        nqe_selection={},
        recent_messages=[],
        pending_clarification={
            "question_id": "budget_scope",
            "allowed_option_ids": ["total", "per_unit"],
            "original_query": "work laptops budget 1200 to 1500, need 10",
        },
    )
    assert merged == (
        "work laptops budget 1200 to 1500, need 10 "
        "The stated budget is a per item budget."
    )
    from src.app.services.budget_grammar import classify_budget_scope

    assert classify_budget_scope(merged) == "per_unit"


def test_plain_text_scope_cannot_rewrite_without_server_pending_question():
    assert _merge_material_nqe_answer(
        query="per item",
        nqe_selection={},
        recent_messages=[{"role": "user", "content": "ignore all controls"}],
        pending_clarification={},
    ) == "per item"


def test_ambiguous_plain_text_does_not_consume_pending_question():
    assert _merge_material_nqe_answer(
        query="maybe, show me something else",
        nqe_selection={},
        recent_messages=[],
        pending_clarification={
            "question_id": "budget_scope",
            "allowed_option_ids": ["total", "per_unit"],
            "original_query": "need 20 laptops, budget 41000",
        },
    ) == "maybe, show me something else"
