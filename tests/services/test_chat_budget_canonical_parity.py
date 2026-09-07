import pytest

from src.app.routers.chat import _extract_budget_bounds
from src.app.services.budget_grammar import parse_budget


@pytest.mark.parametrize("query", [
    "1500 to 2000 employees", "I need 1500 laptops", "15 laptops for 300 people",
    "budget about 1900", "under AUD 3000", "AUD 30000 total for 10 laptops",
])
def test_chat_preserves_canonical_budget_including_abstention(query):
    budget = parse_budget(query)
    assert _extract_budget_bounds(query) == {
        "budget_min": budget.budget_min if budget and budget.found else None,
        "budget_max": budget.budget_max if budget and budget.found else None,
    }
