"""Run frozen synthetic held-out policy comparisons without supplier effects."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('config/heldout_inventory_benchmark.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    cfg=json.loads(args.config.read_text())
    from src.app.services.synthetic_canonical_replay import materialize_canonical_replay
    from src.app.services.heldout_inventory_benchmark import evaluate
    cases=[]
    for scenario in cfg['scenarios']:
        for seed in cfg['seeds']:
            replay=materialize_canonical_replay(scenario,seed=seed,days=cfg['days'],
                tenant_id='synthetic-benchmark',start_date=date.fromisoformat(cfg['start_date']),
                include_lifecycle_probes=False)
            profile=replay['profile']
            signal=dict(source_id='simulation:supplier-alert:'+scenario,tenant_id='synthetic-benchmark',
                variant_id=profile['target_node_id'],available_at=cfg['signal_available_at'],
                expires_at=cfg['signal_expires_at'],
                lead_time_days=profile['lead_time_mean_days']+profile['shock_lead_time_add_days'])
            result=evaluate(replay,train_days=cfg['train_days'],signals=[signal])
            cases.append(dict(scenario=scenario,seed=seed,**result))
    report=dict(manifest=cfg,manifest_digest=hashlib.sha256(args.config.read_bytes()).hexdigest(),
        cases=cases,quality_winner=None,production_roi_claim=False,commerce_authority='none')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(cases),heldout_days_per_case=cfg['days']-cfg['train_days'],quality_winner=None)))


if __name__=='__main__':
    main()
