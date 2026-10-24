from copy import deepcopy
from datetime import date
import pytest
from src.app.services.synthetic_canonical_replay import materialize_canonical_replay
from src.app.services import heldout_inventory_benchmark as benchmark


def fixture():
    return materialize_canonical_replay('electronics_memory_allocation',seed=41,days=300,
        tenant_id='synthetic-benchmark',start_date=date(2025,12,5),include_lifecycle_probes=False)


def test_future_outcomes_cannot_change_frozen_forecasts_or_policies():
    replay=fixture()
    first=benchmark.evaluate(replay,train_days=240)
    changed=deepcopy(replay)
    for row in changed['history']['daily_history'][240:]:
        row['observed_sales_units']=9999
        row['latent_demand_units']=9999
    second=benchmark.evaluate(changed,train_days=240)
    assert first['frozen_policies']==second['frozen_policies']
    assert first['uncertainty']['interval']==second['uncertainty']['interval']
    assert first['uncertainty']['heldout_coverage'] != second['uncertainty']['heldout_coverage']
    assert first['outcomes']!=second['outcomes']
    assert first['test_days']==60
    assert first['commerce_authority']=='none'
    assert first['quality_winner'] is None


def test_signal_must_be_available_before_training_cutoff():
    replay=fixture()
    late=[{'source_id':'simulation:late','available_at':'2026-12-01T00:00:00+00:00','lead_time_days':30,
           'tenant_id':'synthetic-benchmark','variant_id':replay['profile']['target_node_id'],
           'expires_at':'2027-01-01T00:00:00+00:00'}]
    out=benchmark.evaluate(replay,train_days=240,signals=late)
    assert out['signal_receipt']['admitted']==[]
    assert out['signal_receipt']['rejected'][0]['reason']=='not_available_at_cutoff'
    assert out['frozen_policies']['ewma']==out['frozen_policies']['ewma_with_signals']
    assert all('total_cost_minor' in row and 'stockout_days' in row and 'average_on_hand_units' in row for row in out['outcomes'].values())


def test_zero_demand_has_explicit_undefined_service_metric_and_no_phantom_orders():
    replay=fixture()
    for row in replay['history']['daily_history']:
        row.update(observed_sales_units=0,latent_demand_units=0,closing_on_hand_units=0)
    result=benchmark.evaluate(replay,train_days=240)
    for outcome in result['outcomes'].values():
        assert outcome['fill_rate'] is None
        assert outcome['lost_units']==0
        assert outcome['purchase_orders']==0
        assert outcome['total_cost_minor']==0


def test_rolling_origins_have_fixed_horizons_and_future_changes_do_not_leak():
    replay=fixture()
    results=benchmark.evaluate_rolling(replay,origins=[120,180,240],horizon=28)
    assert len(results)==3 and all(row['test_days']==28 for row in results)
    changed=deepcopy(replay)
    for row in changed['history']['daily_history'][148:]:
        row.update(observed_sales_units=999,latent_demand_units=999)
    rerun=benchmark.evaluate_rolling(changed,origins=[120],horizon=28)
    assert rerun[0]['input_digest']==results[0]['input_digest']
    assert rerun[0]['outcomes']==results[0]['outcomes']


def test_realized_supplier_delays_change_scoring_not_policy_inputs():
    replay=fixture()
    fast=benchmark.evaluate(replay,train_days=240,realized_lead_times=[1,2,1])
    disrupted=benchmark.evaluate(replay,train_days=240,realized_lead_times=[30,45,60])
    assert fast['input_digest']==disrupted['input_digest']
    assert fast['frozen_policies']==disrupted['frozen_policies']
    assert fast['uncertainty']==disrupted['uncertainty']
    assert fast['outcomes']!=disrupted['outcomes']
    assert disrupted['evaluation_assumptions']['realized_lead_times']==[30,45,60]
    assert disrupted['evaluation_assumptions']['supplier_delay']=='common_order_ordinal_cycle'
    assert fast['quality_winner'] is None


@pytest.mark.parametrize('delays',[[],[0],[-1],[True],[1.5],[366]])
def test_invalid_realized_delays_are_not_silently_coerced(delays):
    with pytest.raises(ValueError,match='realized_supplier_delays_invalid'):
        benchmark.evaluate(fixture(),train_days=240,realized_lead_times=delays)


def test_rolling_origins_preserve_explicit_scoring_delay_schedule():
    results=benchmark.evaluate_rolling(fixture(),origins=[120,180,240],realized_lead_times=[3,10,4])
    assert all(row['evaluation_assumptions']['realized_lead_times']==[3,10,4] for row in results)
