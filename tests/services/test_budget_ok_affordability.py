from src.app.services.budget_grammar import interpret_price_intent, parse_budget


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


def test_display_intent_distinguishes_limit_target_and_affordability():
    limit = interpret_price_intent("Keep it under $4,000")
    target = interpret_price_intent("I need a laptop around $4,000")
    question = interpret_price_intent("Would $4,000 be enough?")

    assert limit is not None and limit.mode == "hard_ceiling"
    assert target is not None and target.mode == "target_band" and target.target == 4000
    assert question is not None and question.mode == "affordability_check"
    assert (question.preferred_min, question.preferred_max, question.hard_ceiling) == (3000, 4000, 4000)


def test_excessive_for_named_workload_retains_budget_and_affordability_semantics():
    query = "Is AUD 3,000 excessive for Baldur’s Gate 3"
    parsed = parse_budget(query)
    intent = interpret_price_intent(query)

    assert parsed is not None
    assert (parsed.budget_min, parsed.budget_max, parsed.mode) == (None, 3000, "ceiling")
    assert intent is not None
    assert (intent.mode, intent.target, intent.hard_ceiling) == (
        "affordability_check", 3000, 3000,
    )


def test_want_to_spend_around_is_a_target_band_not_a_hard_ceiling():
    query = "I want to spend around AUD 3,000."
    parsed = parse_budget(query)
    intent = interpret_price_intent(query)

    assert parsed is not None
    assert (parsed.budget_min, parsed.budget_max, parsed.mode) == (2400, 3600, "around")
    assert intent is not None
    assert (intent.mode, intent.target, intent.preferred_min, intent.preferred_max) == (
        "target_band", 3000, 2400, 3600,
    )
