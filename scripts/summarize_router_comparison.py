"""Separate pipeline correctness, model-backed answers and setup errors."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.app.services.recommendation_core.envelope import LANES


def summarize(runs, cohort):
    raw = Path(cohort).read_bytes()
    manifest = json.loads(raw)
    excluded = {row['id']: 'label_outside_runtime_lane_vocabulary' for row in manifest['cases']
                if not set(row.get('expected_lanes', [])) <= set(LANES)}
    groups = {}
    for run in runs:
        if run['exit_code']:
            raise ValueError('incomplete_comparison_run')
        result = json.loads(Path(run['artifact']).read_text(encoding='utf-8'))
        if result['cohort_sha256'] != hashlib.sha256(raw).hexdigest():
            raise ValueError('cohort_changed_between_runs')
        group = groups.setdefault(result['model'], {'run_count':0, 'rows':[], 'warmups':[]})
        group['run_count'] += 1
        group['warmups'].append(result.get('warmup'))
        group['rows'].extend(row for row in result['results'] if row['id'] not in excluded)
    for group in groups.values():
        rows = group.pop('rows')
        elapsed = sorted(row['elapsed_ms'] for row in rows)
        model_rows = [row for row in rows if row['source'].startswith('model')]
        group.update(observations=len(rows), unique_cases=len({r['id'] for r in rows}),
            pipeline_lane_matches=sum(r['correct'] for r in rows),
            model_backed_answers=len(model_rows), model_backed_lane_matches=sum(r['correct'] for r in model_rows),
            fallback_count=sum(r['source'].startswith('fallback') for r in rows),
            deterministic_count=sum(r['source'].startswith('deterministic') for r in rows),
            median_elapsed_ms=statistics.median(elapsed),
            p95_elapsed_ms=elapsed[math.ceil(.95*len(elapsed))-1],
            failures=[{'id':r['id'],'source':r['source'],'actual_lane':r['actual_lane']}
                      for r in rows if not r['correct'] or r['source'].startswith('fallback')])
    return {'cohort_sha256':hashlib.sha256(raw).hexdigest(), 'excluded_setup_errors':excluded,
            'models':groups, 'promotion_authorized':False,
            'limitations':['Historical scenario coverage, not independently reviewed production labels.',
                'Repeated observations are not additional independent cases.',
                'Timings include routing, taxonomy/embedding work and fallback; they are not pure inference timings.',
                'Original raw scores include invalid-label cases; only this vocabulary-filtered summary is comparable.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--cohort', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(json.loads(args.runs.read_text(encoding='utf-8')), args.cohort)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
