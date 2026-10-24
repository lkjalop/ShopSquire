"""Equal-window synthetic forecasting stress test; never grants commerce authority."""
import argparse
from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.app.services.synthetic_canonical_replay import materialize_canonical_replay
from src.app.services.heldout_inventory_benchmark import evaluate_rolling


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--variable-deliveries',action='store_true',
        help='Score every policy against the same explicit order-ordinal supplier delay cycle')
    args=parser.parse_args()
    manifest=dict(version=2,seeds=[41,73,109],origins=[120,180,240],horizon=28,days=300,
        supplier_delays='variable_order_cycle' if args.variable_deliveries else 'fixed_at_cutoff',
        regimes=['observed','intermittent','zero'],signals=['none','plausible','noisy','misleading','delayed','expired'],
        training_budget=28,scenarios=['electronics_memory_allocation','packaging_resin_freight','perishable_cold_chain'])
    rows=[]
    # Regime modifications are explicit stress fixtures, not claimed as a
    # reconciled physical history. Scoring never exposes latent demand to policy.
    for scenario in manifest['scenarios']:
      for seed in manifest['seeds']:
       original=materialize_canonical_replay(scenario,seed=seed,days=manifest['days'],
           tenant_id='synthetic-rolling-benchmark',start_date=date(2025,12,5),include_lifecycle_probes=False)
       lead=int(original['profile']['lead_time_mean_days'])
       delays=[max(1,lead-2),lead,lead+7,lead+14,lead] if args.variable_deliveries else None
       for regime in manifest['regimes']:
        replay=deepcopy(original)
        for i,day in enumerate(replay['history']['daily_history']):
            if regime=='zero' or (regime=='intermittent' and i%7):
                day.update(observed_sales_units=0,latent_demand_units=0)
            if regime=='zero':day['closing_on_hand_units']=0
        for variant in manifest['signals']:
          signals=[]
          if variant!='none':
            signals=[dict(source_id='simulation:signal:'+variant,tenant_id=replay['manifest']['tenant_id'],
                variant_id=replay['profile']['target_node_id'],lead_time_days=60 if variant=='misleading' else replay['profile']['lead_time_mean_days'],
                available_at='2030-01-01T00:00:00+00:00' if variant=='delayed' else '2025-12-05T00:00:00+00:00',
                expires_at='2026-01-01T00:00:00+00:00' if variant=='expired' else '2027-01-01T00:00:00+00:00')]
            if variant=='noisy':
                signals[0]['lead_time_days']=max(1,min(60,signals[0]['lead_time_days']+(seed%7)-3))
          for result in evaluate_rolling(replay,origins=manifest['origins'],horizon=manifest['horizon'],
                  signals=signals,realized_lead_times=delays):
            baseline=result['outcomes']['mean_28']
            deltas={name:dict(cost_delta=row['total_cost_minor']-baseline['total_cost_minor'],
                lost_units_delta=row['lost_units']-baseline['lost_units'],
                excess_units_delta=row['average_on_hand_units']-baseline['average_on_hand_units'])
                for name,row in result['outcomes'].items()}
            rows.append(dict(scenario=scenario,seed=seed,regime=regime,signal_variant=variant,deltas=deltas,**result))
    summary={name:dict(lower_cost_cases=sum(row['deltas'][name]['cost_delta']<0 for row in rows),
        higher_cost_cases=sum(row['deltas'][name]['cost_delta']>0 for row in rows),
        mean_cost_delta=statistics.fmean(row['deltas'][name]['cost_delta'] for row in rows))
        for name in ('ewma','ewma_with_signals')}
    report=dict(manifest=manifest,cases=rows,summary=summary,quality_winner=None,commerce_authority='none',
        limitations=['Synthetic stress scenarios; no real business ROI','No foundation-model challenger installed',
            'Explicit synthetic supplier delays; customer-specific deadline performance not certified',
            'Variable delays cycle by order ordinal, not a calendar disruption shared across policies',
            'Forecast compute timing excludes ingestion and model loading','No independent external label review'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(rows),summary=summary,quality_winner=None)))


if __name__=='__main__':main()
