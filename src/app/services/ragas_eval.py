from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import text as sql_text
from src.app.models.db import db_session
from src.app.platform.tenant_context import current_tenant_id
from src.app.observability.metrics import record_ragas_eval
from src.app.services.evaluation_contract import CONTRACT_VERSION, METRICS, evaluate_sample, persist_evaluation


def _compute_ragas_like(input_data: Any, context: Any, answer: Any) -> dict[str, float | None]:
    """Compatibility entrypoint: unavailable measurement has no numerical score."""
    return evaluate_sample(input_data, context, answer)['metrics']


def _decode(value: Any) -> Any:
    if not isinstance(value, str):
        return value or {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def evaluate_and_persist(decision_id: str) -> dict[str, Any]:
    tenant = current_tenant_id()
    with db_session() as db:
        row = db.execute(sql_text('''SELECT input_data, retrieved_context, proposed_action
            FROM decision_logs WHERE id = :id AND tenant_id = :tenant'''),
            {'id': decision_id, 'tenant': tenant}).fetchone()
        if row is None:
            return {'evaluated': False, 'error': 'decision_not_found'}
        result = evaluate_sample(*[_decode(value) for value in row])
        try:
            persist_evaluation(db, result, decision_id=decision_id, tenant_id=tenant)
            db.commit()
        except Exception:
            db.rollback()
            record_ragas_eval('persistence_error')
            raise
    record_ragas_eval(result['status'])
    return {'evaluated': result['status'] == 'evaluated', 'decision_id': decision_id, **result}


def run_sampling(sample_rate: float = 0.1, limit: int = 200) -> dict[str, Any]:
    import random
    if not 0 <= sample_rate <= 1 or not 1 <= limit <= 10000:
        raise ValueError('invalid_sampling_window')
    with db_session() as db:
        rows = db.execute(sql_text('''SELECT id FROM decision_logs WHERE tenant_id = :tenant
            ORDER BY created_at DESC LIMIT :limit'''),
            {'tenant': current_tenant_id(), 'limit': limit}).fetchall()
    counts = {'evaluated': 0, 'unavailable': 0, 'error': 0, 'not_evaluated': 0}
    for (decision_id,) in rows:
        if random.random() > sample_rate:
            continue
        try:
            result = evaluate_and_persist(decision_id)
            status = result.get('status', 'error')
        except Exception:
            status = 'error'
        counts[status if status in counts else 'error'] += 1
    return {**counts, 'sampled': len(rows), 'sample_rate': sample_rate,
            'ok': counts['evaluated'] > 0 and not any(counts[k] for k in counts if k != 'evaluated')}


def thresholds_to_confidence(metrics: dict[str, Any], faith_min: float = .75, recall_min: float = .6):
    values = [metrics.get('faithfulness'), metrics.get('context_recall')]
    valid = all(type(v) in (int, float) and math.isfinite(v) for v in values)
    ok = valid and values[0] >= faith_min and values[1] >= recall_min
    return bool(ok), 1.0 if ok else .8


def recent_evaluations(db, window: int = 200):
    return db.execute(sql_text('''SELECT faithfulness, answer_relevance, context_precision,
        context_recall, created_at, evaluation_status, metadata_json, evaluator_model
        FROM ragas_eval_results WHERE tenant_id = :tenant ORDER BY created_at DESC LIMIT :window'''),
        {'tenant': current_tenant_id(), 'window': window}).fetchall()


def evaluation_summary(db) -> dict[str, Any]:
    rows = recent_evaluations(db)
    measured = [r for r in rows if r[5] == 'evaluated' and r[7] == CONTRACT_VERSION
                and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in r[:4])]
    return {'count': len(rows), 'evaluated_count': len(measured), 'unmeasured_count': len(rows) - len(measured),
        'status': 'measured' if measured else 'no_measurements',
        'averages': {name: sum(r[i] for r in measured) / len(measured) if measured else None
                     for i, name in enumerate(METRICS)}}


def ci_guard_check(window: int = 200, drop_pct: float = .1) -> dict[str, Any]:
    if not 1 <= window <= 10000 or not 0 <= drop_pct < 1:
        raise ValueError('invalid_evaluation_gate_window')
    with db_session() as db:
        rows = recent_evaluations(db, window)
        if not rows:
            return {'ok': False, 'reason': 'no_data'}
        baseline = db.execute(sql_text('''SELECT baseline_score, metadata_json FROM ragas_baseline
            WHERE id = :id AND tenant_id = :tenant'''),
            {'id': current_tenant_id(), 'tenant': current_tenant_id()}).fetchone()
        if not baseline:
            return {'ok': False, 'reason': 'approved_baseline_required'}
        policy = _decode(baseline[1])
        keys = ('dataset_id', 'model_id', 'prompt_version', 'config_hash', 'evaluator_version')
        if (not isinstance(policy, dict) or not policy.get('approved_by') or not policy.get('approved_at')
                or not all(policy.get(key) for key in keys)):
            return {'ok': False, 'reason': 'approved_baseline_required'}
        score = baseline[0]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 < score <= 1:
            return {'ok': False, 'reason': 'invalid_baseline'}
        now = datetime.now(timezone.utc)
        valid = []
        for row in rows:
            metadata = _decode(row[6])
            if row[5] != 'evaluated' or row[7] != CONTRACT_VERSION or not isinstance(metadata, dict):
                continue
            if any(metadata.get(k) != policy[k] for k in keys):
                continue
            try:
                stamp = datetime.fromisoformat(str(row[4]).replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if not 0 <= (now - stamp).total_seconds() <= float(policy.get('max_age_seconds', 86400)):
                    continue
            except (ValueError, TypeError):
                continue
            if all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in row[:4]):
                valid.append(row)
        minimum = max(1, int(policy.get('min_samples', 40)))
        if len(valid) < minimum:
            return {'ok': False, 'reason': 'insufficient_fresh_measurements', 'count': len(valid), 'required': minimum}
        avg = sum((row[0] + row[3]) / 2 for row in valid) / len(valid)
        return {'ok': avg >= (1 - drop_pct) * score,
            'reason': 'passed' if avg >= (1 - drop_pct) * score else 'moving_avg_drop',
            'avg': avg, 'baseline': score, 'count': len(valid)}
