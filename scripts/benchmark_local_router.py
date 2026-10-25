"""Run the real router on a frozen smoke cohort without mutating commerce state."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def validate_cases(cases):
    from src.app.services.recommendation_core.envelope import LANES
    for case in cases:
        expected = case.get('expected_lanes', [case.get('expected_lane')])
        if not expected or not set(expected) <= set(LANES):
            raise ValueError(f"invalid_cohort_lane_label:{case['id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--endpoint', default='http://127.0.0.1:11435')
    parser.add_argument('--cohort', type=Path, default=ROOT / 'config/benchmarks/router_roadmap_holdout.json')
    parser.add_argument('--warmup', action='store_true')
    args = parser.parse_args()
    cohort = args.cohort
    raw = cohort.read_bytes()
    cases = json.loads(raw)['cases']
    validate_cases(cases)
    tags = requests.get(args.endpoint + '/api/tags', timeout=5).json()['models']
    digest = next(row['digest'] for row in tags if row['name'] == args.model)
    os.environ.update(ROUTER_MODEL=args.model, ROUTER_MODEL_DIGEST=digest,
        OLLAMA_URL=args.endpoint, ROUTER_MODEL_ENABLED='1', USE_MOCK_LLM='0',
        OLLAMA_CONTEXT_LENGTH='4096', OLLAMA_KEEP_ALIVE='2m', LOCAL_MODEL_MAX_CONCURRENCY='1')
    from src.app.models.db import db_session
    from src.app.services.recommendation_core.envelope import TurnEnvelope
    from src.app.services.recommendation_core.turn_router import route_turn
    from src.app.services.local_model_roles import last_local_model_schedule_metrics
    warmup = None
    if args.warmup:
        tick = time.perf_counter()
        response = requests.post(args.endpoint+'/api/generate', json={'model':args.model,
            'prompt':'Reply with one word: ready.', 'think':False, 'stream':False,
            'keep_alive':'2m', 'options':{'num_ctx':4096,'num_predict':32}},timeout=60)
        response.raise_for_status()
        warmup = {'elapsed_ms':round((time.perf_counter()-tick)*1000), 'done':response.json().get('done')}
    results = []
    with db_session() as db:
        for case in cases:
            previous_schedule = last_local_model_schedule_metrics()
            started = time.perf_counter()
            decision = route_turn(db, TurnEnvelope(tenant_id='default', uid='router-benchmark',
                query=case['query'], trace_id='benchmark-'+uuid.uuid4().hex, currency='AUD'), timeout=40)
            schedule = last_local_model_schedule_metrics()
            result = {**case, 'actual_lane': decision.lane, 'source': decision.source,
                'correct': decision.lane in case.get('expected_lanes', [case.get('expected_lane')]),
                'elapsed_ms': round((time.perf_counter()-started)*1000,2),
                'schedule': schedule if schedule != previous_schedule else None}
            results.append(result)
            print(json.dumps({k:result[k] for k in ('id','actual_lane','correct','elapsed_ms')}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'model':args.model, 'artifact_digest':digest,
        'cohort_sha256':hashlib.sha256(raw).hexdigest(), 'context_length':4096, 'warmup':warmup,
        'cohort_review_status':json.loads(raw).get('review_status'),
        'correct':sum(r['correct'] for r in results), 'total':len(results), 'results':results,
        'limitation':'Routing cohort only; no independent held-out commerce-outcome improvement established.'},indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
