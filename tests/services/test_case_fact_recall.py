import pytest

from src.app.services.case_task_delivery import is_case_task_read


@pytest.mark.parametrize('query', [
    'Summarise my quantity, per-unit budget and delivery destination without taking any action.',
    'How many laptops did I ask for and what was my budget and delivery destination?',
    'Remind me of my requested quantity and budget.',
    'Recap my current request.',
])
def test_owned_fact_recall_is_read_only(query):
    assert is_case_task_read(query, {'requested_quantity': 40}) is True


@pytest.mark.parametrize('query', [
    'Summarise my request and deliver to Melbourne.',
    'Recap my request; I need them by Friday.',
    'Summarise my request and approve the order.',
    'Summarise my request and pay the deposit.',
    'Summarise my request and also use Blender.',
    'Remind me of my budget and change it to AUD 2000.',
    'Summarise my request; my budget is now AUD 2000.',
    'Summarise my request for 50 units.',
    'Summarise my request and search for official requirements.',
    'Summarise my request and check the official sources.',
    'Remind me of my password.',
    'Summarise the official FreeCAD features.',
])
def test_fact_recall_cannot_swallow_amendments_or_unrelated_requests(query):
    assert is_case_task_read(query, {'requested_quantity': 40}) is False
