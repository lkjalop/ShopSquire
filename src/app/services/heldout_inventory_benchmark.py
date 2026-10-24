"""Frozen observed-data policies scored on a separate synthetic future.

Latent demand is used only by the environment to measure missed demand. It is
never provided to the baseline, EWMA challenger, or signal admission function.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import statistics
import time

from src.app.services.demand_forecast import _ewma_one
from src.app.services.synthetic_policy_counterfactual import _simulate_policy


def evaluate(replay, *, train_days, signals=(), realized_lead_times=None):
    history = replay['history']['daily_history']
    if not 28 <= train_days <= len(history)-28:
        raise ValueError('separate_training_and_test_windows_required')
    profile = replay['profile']
    training, heldout = history[:train_days], history[train_days:]
    cutoff = datetime.fromisoformat(training[-1]['date']+'T23:59:59+00:00')
    observed = [row['observed_sales_units'] for row in training]
    tick=time.perf_counter()
    naive = statistics.fmean(observed[-28:])
    ewma = _ewma_one(observed[-28:])
    forecast_ms=(time.perf_counter()-tick)*1000
    # Descriptive training quantiles, explicitly not a calibrated guarantee.
    # Censored sales can understate demand; held-out coverage exposes that gap.
    ordered = sorted(observed[-28:])
    interval = [ordered[math.floor(.1*(len(ordered)-1))],
                ordered[math.ceil(.9*(len(ordered)-1))]]
    lead=int(profile['lead_time_mean_days'])
    admitted, rejected = [], []
    signal_lead=lead
    for signal in signals:
        reason=None
        if (signal.get('tenant_id')!=replay['manifest']['tenant_id']
                or signal.get('variant_id')!=profile['target_node_id']
                or not str(signal.get('source_id','')).startswith('simulation:')):
            reason='signal_scope_or_provenance_mismatch'
        else:
            try:
                available=datetime.fromisoformat(signal['available_at'].replace('Z','+00:00'))
                expires=datetime.fromisoformat(signal['expires_at'].replace('Z','+00:00'))
                if available.tzinfo is None or expires.tzinfo is None:
                    raise ValueError('timezone_required')
                if available>cutoff:reason='not_available_at_cutoff'
                elif expires<=cutoff:reason='expired_at_cutoff'
                elif type(signal.get('lead_time_days')) is not int or not 1<=signal['lead_time_days']<=60:
                    reason='invalid_lead_time'
            except (KeyError, ValueError, TypeError):
                reason='invalid_signal'
        if reason:
            rejected.append(dict(source_id=signal.get('source_id'),reason=reason))
        else:
            admitted.append(signal['source_id'])
            signal_lead=max(signal_lead,signal['lead_time_days'])
    def policy(mean, horizon):
        return dict(reorder_point=math.ceil(mean*(horizon+3)),
                    reorder_quantity=int(profile['reorder_quantity']) if mean>0 else 0,
                    mean_daily=mean,lead_time_days=horizon)
    policies=dict(mean_28=policy(naive,lead),ewma=policy(ewma,lead),
                  ewma_with_signals=policy(ewma,signal_lead))
    # Scoring parameters are common across policies. Future physical demand and
    # realized supplier delay belong only to this environment, not policy inputs.
    demand=[row['latent_demand_units'] for row in heldout]
    actual_lead=lead+(int(profile['shock_lead_time_add_days']) if train_days>=int(profile['shock_day']) else 0)
    if realized_lead_times is not None and (not isinstance(realized_lead_times,(list,tuple))
            or not realized_lead_times or any(type(n) is not int or not 1<=n<=365 for n in realized_lead_times)):
        raise ValueError('realized_supplier_delays_invalid')
    # Environment-only realizations: identical order-ordinal cycle for every
    # candidate, never admitted as a forecast input or an external signal.
    scoring_delays=list(realized_lead_times) if realized_lead_times is not None else [actual_lead]
    unit_cost=int(profile['unit_cost_minor'])
    sale_price=int(profile.get('current_price_minor') or unit_cost*1.5)
    outcomes={}
    for name,p in policies.items():
        row=_simulate_policy(demand=demand,initial_inventory=training[-1]['closing_on_hand_units'],
            reorder_point=p['reorder_point'],reorder_quantity=p['reorder_quantity'],
            lead_times=scoring_delays,unit_cost_minor=unit_cost,sale_price_minor=sale_price,
            shock_day=max(0,int(profile['shock_day'])-train_days),
            shock_unit_cost_minor=round(unit_cost*(1+float(profile['shock_cost_pass_through_pct'])/100)),
            shelf_life_days=profile.get('shelf_life_days'))
        # Explicit, frozen scenario cost assumptions, not measured business ROI.
        holding=round(row['average_on_hand_units']*len(heldout)*unit_cost*0.0005)
        shortage=row['lost_units']*max(0,sale_price-unit_cost)
        row.update(holding_cost_minor=holding,shortage_penalty_minor=shortage,
                   total_cost_minor=row['purchase_spend_minor']+holding+shortage)
        outcomes[name]=row
    fingerprint=hashlib.sha256(json.dumps(dict(observed=observed,cutoff=cutoff.isoformat(),
        policies=policies,admitted_signals=admitted),sort_keys=True).encode()).hexdigest()
    return dict(train_days=train_days,test_days=len(heldout),cutoff=cutoff.isoformat(),
        first_test_date=heldout[0]['date'],last_test_date=heldout[-1]['date'],
        input_digest=fingerprint,training_censored_days=sum(row['closing_on_hand_units']==0 for row in training),
        frozen_policies=policies,outcomes=outcomes,forecast_compute_ms=forecast_ms,
        uncertainty=dict(method='training_empirical_10_90', interval=interval,
            target='daily_latent_demand', nominal_coverage=.8,
            heldout_coverage=sum(interval[0]<=value<=interval[1] for value in demand)/len(demand),
            calibrated=False, caveat='Observed sales are censored; quantiles are diagnostic only'),
        signal_receipt=dict(admitted=admitted,rejected=rejected),
        evaluation_assumptions=dict(initial_incoming_units=0,initial_stock='last_training_close',
            daily_holding_cost_fraction=0.0005,shortage_penalty='unit_margin',
            supplier_delay='common_order_ordinal_cycle' if realized_lead_times is not None else 'fixed_scenario_delay_at_cutoff',
            realized_lead_times=scoring_delays,forecast_input='28_observed_days_for_each_model'),
        quality_winner=None,simulation_only=True,commerce_authority='none')


def evaluate_rolling(replay, *, origins, horizon=28, signals=(), realized_lead_times=None):
    """Identical future window and training budget at every predeclared origin."""
    if type(horizon) is not int or horizon<28 or not origins:
        raise ValueError('bounded_rolling_windows_required')
    history=replay['history']['daily_history']
    if len(set(origins))!=len(origins) or any(type(n) is not int or n<28 or n+horizon>len(history) for n in origins):
        raise ValueError('invalid_rolling_origin')
    results=[]
    for origin in origins:
        window={**replay,'history':{**replay['history'],'daily_history':history[:origin+horizon]}}
        results.append(evaluate(window,train_days=origin,signals=signals,realized_lead_times=realized_lead_times))
    return results
