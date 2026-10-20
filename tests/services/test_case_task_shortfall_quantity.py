"""A shortage count describes a task, not an amendment of total buyer demand."""
import pytest

from src.app.services.case_task_delivery import is_case_task_read


@pytest.mark.parametrize('query', [
    'Draft an email to the supplier for the 25 unit shortfall.',
    'Draft an email about the shortfall of 25 units.',
    'Write a supplier email for the twenty-five unit shortage.',
    'Compose a supplier email for the remaining 25 units.',
    'Give me market analysis for the 25 unit shortfall in my current request.',
])
def test_shortfall_task_quantity_does_not_replace_requested_quantity(query):
    assert is_case_task_read(query, {'requested_quantity': 40}) is True


@pytest.mark.parametrize('query', [
    'Make it 50 units and draft a supplier email for the 25 unit shortfall.',
    'Draft an email for the 25 unit shortfall, and request 50 units in total.',
    'Draft an email for 50 units.',
    'Give me market analysis and increase my request to 50 units.',
    'Write an email to reset my password.',
])
def test_total_amendments_and_unrelated_mail_keep_the_normal_intake(query):
    assert is_case_task_read(query, {'requested_quantity': 40}) is False
