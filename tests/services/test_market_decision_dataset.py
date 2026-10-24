from datetime import date
import pytest

from src.app.services.synthetic_canonical_replay import materialize_canonical_replay


def test_catalog_bound_replay_preserves_calendar_currency_and_conservation():
    replay = materialize_canonical_replay(
        'electronics_memory_allocation', seed=41, days=180,
        tenant_id='synthetic-market-pilot', start_date=date(2026, 4, 4),
        target_variant_id='LAP-01B48B57', currency='AUD',
    )
    assert replay['history']['daily_history'][0]['date'] == '2026-04-04'
    assert replay['profile']['target_node_id'] == 'LAP-01B48B57'
    assert replay['manifest']['catalog_binding']['currency'] == 'AUD'
    for observation in replay['observations']:
        if 'variant_id' in observation.payload:
            assert observation.payload['variant_id'] == 'LAP-01B48B57'
        for field in ('total', 'unit_price', 'unit_cost'):
            if field in observation.payload:
                assert observation.payload[field]['currency'] == 'AUD'
    for day in replay['history']['daily_history']:
        assert day['closing_on_hand_units'] == day['opening_on_hand_units'] + day['receipt_units'] - day['observed_sales_units']


def test_binding_changes_fingerprint_and_production_tenant_is_rejected():
    kwargs=dict(seed=41, days=40, tenant_id='synthetic-market-pilot')
    a=materialize_canonical_replay('electronics_memory_allocation', target_variant_id='SKU-A', **kwargs)
    b=materialize_canonical_replay('electronics_memory_allocation', target_variant_id='SKU-B', **kwargs)
    assert a['manifest']['parameter_hash'] != b['manifest']['parameter_hash']
    with pytest.raises(ValueError, match='synthetic'):
        materialize_canonical_replay('electronics_memory_allocation', seed=41, days=40,
                                    tenant_id='real-shop', target_variant_id='SKU-A')


def test_pilot_excludes_deliberate_fault_probes_and_reconciles():
    replay = materialize_canonical_replay('electronics_memory_allocation', seed=41, days=180,
        tenant_id='synthetic-market-pilot', start_date=date(2026,4,4),
        target_variant_id='LAP-01B48B57', currency='AUD', include_lifecycle_probes=False)
    assert replay['inventory_projection']['balance_integrity']['status'] == 'passed'
    assert replay['inventory_projection']['atp_reconciliation']['status'] == 'matched'
    assert replay['manifest']['catalog_binding']['include_lifecycle_probes'] is False
