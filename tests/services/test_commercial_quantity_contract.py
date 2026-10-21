import json
import pytest
from src.app.platform import store_profile
from src.app.services.commercial_terms import parse_commercial_terms
from src.app.services.bulk_intent import extract_quantity_span


@pytest.mark.parametrize('query', ['dell 15 laptop under 1400', '15 inch laptops under 1400',
                                  'need 16 GB laptops', 'RGAM-0007 laptops'])
def test_specifications_and_model_identifiers_are_not_order_counts(query):
    assert parse_commercial_terms(query).quantity is None


def test_large_observed_count_does_not_raise_default_procurement_limit():
    assert parse_commercial_terms('1,200 units at $100 each').quantity == 1200
    assert extract_quantity_span('1200 units') is None


def test_industrial_count_uses_profile_and_shared_dimension_guard(tmp_path, monkeypatch):
    (tmp_path / 'industrial.json').write_text(json.dumps({
        'id': 'industrial', 'commercial_quantity_units': {'valves': 'valve', 'valve': 'valve'},
    }), encoding='utf-8')
    monkeypatch.setenv('STORE_PROFILES_DIR', str(tmp_path))
    store_profile.reset_cache()
    token = store_profile.set_active_profile_id('industrial')
    try:
        parsed = parse_commercial_terms('30 valves at $15 each')
        assert (parsed.quantity, parsed.quantity_unit) == (30, 'valve')
        assert parse_commercial_terms('valve 30 units').quantity is None
    finally:
        store_profile.reset_active_profile_id(token)
        store_profile.reset_cache()
@pytest.mark.parametrize('query',[
    'Change the laptop quantity to 12, keeping my AUD 1500 per laptop budget.',
    'Set the valve quantity to 12.',
    'quantity: 12', 'qty = 12',
])
def test_explicit_quantity_label_can_bind_a_correction(query):
    from src.app.services.bulk_intent import extract_quantity_span
    assert extract_quantity_span(query)==(12,'12')


@pytest.mark.parametrize('query',['quantity to 12.5', 'quantity to 12.A', 'quantity to 12/15'])
def test_explicit_label_does_not_truncate_fraction_or_identifier(query):
    assert extract_quantity_span(query) is None
