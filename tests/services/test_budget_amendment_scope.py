import pytest

from src.app.services import budget_grammar


@pytest.mark.parametrize('query,expected', [
    ('cut it to 1000 max', True),
    ('actually budget is now 1800 max', True),
    ('actually make it AUD 2000', True),
    ('under AUD 2000', True),
    ('a chair under AUD 400', False),
    ('actually make it a chair under AUD 400', False),
    ('forget that, a server under 5000', False),
    ('under 2000 for Blender', False),
    ('10 laptops under 30000 total', False),
    ('keep the budget', False),
])
def test_only_literal_budget_amendments_can_restore_scope(query, expected):
    assert budget_grammar.is_budget_only_amendment(query) is expected
