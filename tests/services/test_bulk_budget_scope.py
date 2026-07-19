from src.app.services.budget_grammar import classify_budget_scope


def test_explicit_whole_order_budget_is_total():
    assert classify_budget_scope("25 laptops; total budget is $41,000") == "total"
    assert classify_budget_scope("$41k all in for the fleet") == "total"


def test_per_unit_language_wins_over_total_words():
    assert classify_budget_scope("$1,600 each, $40,000 total") == "per_unit"


def test_bare_budget_remains_unknown():
    assert classify_budget_scope("budget is $1,600") == "unknown"
