from src.app.services.budget_grammar import (
    classify_budget_scope,
    parse_budget,
    resolve_total_budget_cap,
)


def test_explicit_whole_order_budget_is_total():
    assert classify_budget_scope("25 laptops; total budget is $41,000") == "total"
    assert classify_budget_scope("20 laptops with a total order budget of $14,000") == "total"
    assert classify_budget_scope("I need 30 units. AUD 140000 total.") == "total"
    assert classify_budget_scope("$41k all in for the fleet") == "total"
    assert classify_budget_scope("50 laptops but keep the total under 5 grand") == "total"


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


def test_same_total_budget_reuses_explicit_cents_not_normalized_unit_cap():
    assert resolve_total_budget_cap(
        "keep the same total budget and quantity",
        normalized_budget_max=2050,
        prior_total_budget_cents=4_100_000,
        prior_budget_scope="total",
    ) == 41_000


def test_new_explicit_total_overrides_prior_total():
    assert resolve_total_budget_cap(
        "change the total budget to $50,000",
        normalized_budget_max=50_000,
        prior_total_budget_cents=4_100_000,
        prior_budget_scope="total",
    ) == 50_000
