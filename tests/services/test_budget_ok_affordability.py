from src.app.services.budget_grammar import parse_budget


def test_short_ok_affordability_question_is_a_budget_ceiling():
    parsed = parse_budget("help me with a gaming laptop, is 4000 ok?")

    assert parsed is not None
    assert parsed.budget_min is None
    assert parsed.budget_max == 4000
    assert parsed.mode == "ceiling"


def test_short_ok_measurement_is_not_money():
    assert parse_budget("is 16 GB okay?") is None


def test_singular_product_price_is_a_target_band_not_a_ceiling():
    parsed = parse_budget("I need a 4000 laptop for university")
    assert parsed is not None
    assert parsed.mode == "around"
    assert (parsed.budget_min, parsed.budget_max) == (3200, 4800)
