import pytest
from src.app.services.terminal_qualification import qualified_configuration_ids


@pytest.mark.parametrize('shelves', [None, [], 'invalid', {'shelves': None},
    {'shelves': [None, 'invalid', {'initial': None, 'next_page': 5}]},
    {'shelves': [{'initial': [None, 'invalid', {'fit_status': 'qualified'}]}]}])
def test_malformed_shelves_never_crash_or_qualify(shelves):
    assert qualified_configuration_ids(
        {'catalog_authority': 'permitted', 'requirement_completeness': 'complete'}, shelves) == []


def test_valid_configuration_survives_malformed_neighbors():
    shelves = {'shelves': [None, {'initial': [None, {'fit_status': 'qualified', 'identity_key': 'sku-v1'}],
                                'next_page': ['invalid']}]}
    assert qualified_configuration_ids(
        {'catalog_authority': 'permitted', 'requirement_completeness': 'complete'}, shelves) == ['sku-v1']
