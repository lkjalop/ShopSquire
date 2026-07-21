from src.app.services.budget_grammar import classify_budget_scope, parse_budget


def test_explicit_whole_order_budget_is_total():
    assert classify_budget_scope("25 laptops; total budget is $41,000") == "total"
    assert classify_budget_scope("20 laptops with a total order budget of $14,000") == "total"
    assert classify_budget_scope("$41k all in for the fleet") == "total"


def test_per_unit_language_wins_over_total_words():
    assert classify_budget_scope("$1,600 each, $40,000 total") == "per_unit"


def test_bare_budget_remains_unknown():
    assert classify_budget_scope("budget is $1,600") == "unknown"


def test_affordability_question_is_a_budget_ceiling():
    for query, expected in (
        ("is $1800 enough for a gaming laptop?", 1800),
        ("would 1500 be enough for university?", 1500),
        ("do I have enough at $1000 for a student laptop?", 1000),
    ):
        parsed = parse_budget(query)
        assert parsed is not None, query
        assert parsed.budget_min is None
        assert parsed.budget_max == expected
        assert parsed.mode == "ceiling"
