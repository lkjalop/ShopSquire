from src.app.services.budget_grammar import parse_budget
from src.app.services.recommendation_core.envelope import TurnEnvelope


def test_iso_currency_prefix_is_a_budget_ceiling():
    parsed = parse_budget(
        "I'm at university studying game development using Unreal and Blender; "
        "I need a laptop under AUD 2500."
    )

    assert parsed is not None
    assert parsed.budget_min is None
    assert parsed.budget_max == 2500
    assert parsed.mode == "ceiling"


def test_iso_currency_budget_is_normalized_into_the_turn_envelope():
    envelope = TurnEnvelope.from_suggest_params(
        query="game-development laptop under AUD 2500",
        currency="AUD",
    )

    assert envelope.currency == "AUD"
    assert envelope.budget_max_cents == 250_000


def test_unbounded_three_letter_token_is_not_treated_as_currency():
    assert parse_budget("laptop with RTX 2500 graphics") is None
