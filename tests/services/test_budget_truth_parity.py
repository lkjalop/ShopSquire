import pytest

from src.app.services.answer_quality import _extract_query_budget_bounds
from src.app.services.budget_grammar import canonical_budget_from_accepted_slots, parse_budget
from src.app.services.commercial_terms import parse_commercial_terms
from src.app.services.intent_decomposer import _extract_budget
from src.app.services.recommendation_core.envelope import TurnEnvelope


@pytest.mark.parametrize(
    "query, expected",
    [
        ("ERP for the finance team, budget AUD 2M", (None, 2_000_000)),
        ("Buy 200 CRM seats under AUD 120k annually", (None, 120_000)),
        ("Antivirus for 500 endpoints at $45/device/year", (None, None)),
        ("A workstation for Blender under AUD 5k", (None, 5_000)),
        ("Buy Photoshop licences for 40 designers", (None, None)),
        ("Laptops that can run Photoshop for 40 designers", (None, None)),
    ],
)
def test_query_budget_has_one_truth_across_surfaces(query, expected):
    parsed = parse_budget(query)
    canonical = (
        (parsed.budget_min, parsed.budget_max) if parsed is not None else (None, None)
    )
    intent = _extract_budget(query.lower())[:2]
    quality = _extract_query_budget_bounds(query)
    envelope = TurnEnvelope.from_suggest_params(query=query)
    envelope_value = (
        envelope.budget_min_cents // 100 if envelope.budget_min_cents is not None else None,
        envelope.budget_max_cents // 100 if envelope.budget_max_cents is not None else None,
    )
    assert canonical == intent == quality == envelope_value == expected


def test_per_user_recurring_price_is_commercial_terms_not_a_hardware_budget():
    terms = parse_commercial_terms("Antivirus for 500 endpoints at $45/device/year")
    assert terms.quantity == 500
    assert terms.quantity_unit == "endpoint"
    assert terms.unit_price == 45
    assert terms.billing_cadence == "annual"
    assert terms.recurring_fees == 45


def test_enterprise_budget_and_seat_count_remain_separate():
    env = TurnEnvelope.from_suggest_params(
        query="Buy 200 CRM seats under AUD 120k annually",
    )
    assert env.budget_max_cents == 12_000_000
    assert env.commercial_terms.quantity == 200
    assert env.commercial_terms.quantity_unit == "seat"
    assert env.commercial_terms.billing_cadence == "annual"
    assert env.commercial_terms.currency == "AUD"


def test_physical_bulk_quantity_is_canonical_when_model_is_unavailable():
    env = TurnEnvelope.from_suggest_params(
        query="I need 60 laptops with a total budget of AUD 30,000",
    )

    assert env.commercial_terms.quantity == 60
    assert env.commercial_terms.quantity_unit == "laptop"
    assert env.commercial_terms.budget_scope == "total"


@pytest.mark.parametrize(
    "query",
    [
        "$3000 laptop",
        "will a $3000 laptop run where winds meet?",
        "Is AUD 3,000 excessive for Baldur's Gate 3?",
    ],
)
def test_currency_amount_is_never_reinterpreted_as_item_quantity(query):
    terms = parse_commercial_terms(query)
    assert terms.quantity is None
    assert terms.quantity_unit is None


@pytest.mark.parametrize(
    "query, expected_budget",
    [
        ("on a 2500 laptop", (None, 2500)),
        ("for a 3000 workstation", (None, 3000)),
    ],
)
def test_article_led_bare_product_price_is_not_a_bulk_quantity(
    query, expected_budget,
):
    parsed = parse_budget(query)
    terms = parse_commercial_terms(query)

    assert parsed is not None
    assert (parsed.budget_min, parsed.budget_max) == expected_budget
    assert terms.quantity is None
    assert terms.quantity_unit is None


@pytest.mark.parametrize(
    "query, quantity",
    [
        ("I need 3000 laptops", 3000),
        ("buy 1 workstation", 1),
    ],
)
def test_genuine_physical_order_quantity_survives_price_guard(query, quantity):
    terms = parse_commercial_terms(query)
    assert terms.quantity == quantity


def test_subject_switch_does_not_preemptively_inherit_prior_budget_at_ingress():
    env = TurnEnvelope.from_suggest_params(
        query="What about Rockwell Emulate3D running locally?",
        session={
            "accepted_constraints": {"budget_max_cents": 300_000},
            "currency": "AUD",
        },
    )
    assert env.budget_parse is None
    assert env.budget_max_cents is None


def test_terminal_revision_retains_prior_structured_budget_without_reparsing_switch_text():
    projected = canonical_budget_from_accepted_slots(
        {"budget_min": None, "budget_max": None, "mode": "structured", "source_span": None},
        {"budget_max": 3000, "currency": "AUD"},
    )

    assert projected == {
        "budget_min": None,
        "budget_max": 3000,
        "mode": "ceiling",
        "source_span": None,
    }


def test_current_turn_budget_wins_over_retained_case_budget():
    projected = canonical_budget_from_accepted_slots(
        {"budget_min": 4000, "budget_max": 5000, "mode": "range", "source_span": [5, 20]},
        {"budget_max": 3000},
    )

    assert projected["budget_min"] == 4000
    assert projected["budget_max"] == 5000
