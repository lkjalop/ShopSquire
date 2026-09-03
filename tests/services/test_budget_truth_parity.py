import pytest

from src.app.services.answer_quality import _extract_query_budget_bounds
from src.app.services.budget_grammar import parse_budget
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
