"""One truthful evaluation contract for online decisions and release datasets."""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any
from uuid import uuid4

METRICS = ('faithfulness', 'answer_relevance', 'context_precision', 'context_recall')
CONTRACT_VERSION = 'ragas-v2'


def evaluate_sample(question: Any, context: Any, answer: Any) -> dict[str, Any]:
    metadata = context.get('evaluation', {}) if isinstance(context, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    result = {'eval_id': uuid4().hex, 'status': 'unavailable', 'error_code': None,
        'metrics': dict.fromkeys(METRICS), 'evaluator_model': CONTRACT_VERSION,
        'evaluator_version': None, 'evaluated_at': datetime.now(timezone.utc).isoformat(),
        **{key: metadata.get(key) for key in ('dataset_id', 'model_id', 'prompt_version', 'config_hash')}}
    try:
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
        from datasets import Dataset
    except ImportError:
        result['error_code'] = 'evaluator_unavailable'
        return result
    except Exception as exc:
        result.update(status='error', error_code=type(exc).__name__)
        return result
    try:
        result['evaluator_version'] = version('ragas')
        chunks = (context.get('chunks') or context.get('context_chunks')) if isinstance(context, dict) else None
        reference = context.get('ground_truth') if isinstance(context, dict) else None
        if isinstance(chunks, str):
            chunks = [chunks]
        if not question or not answer or not chunks or not reference:
            result.update(status='not_evaluated', error_code='reference_sample_incomplete')
            return result
        stringify = lambda value: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        dataset = Dataset.from_list([{'question': stringify(question), 'answer': stringify(answer),
            'contexts': [stringify(chunk) for chunk in chunks], 'ground_truth': stringify(reference)}])
        measured = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_precision, context_recall])
        values = {name: float(measured['answer_relevancy' if name == 'answer_relevance' else name][0]) for name in METRICS}
        if not all(math.isfinite(value) and 0 <= value <= 1 for value in values.values()):
            raise ValueError('invalid_evaluator_scores')
        result.update(status='evaluated', metrics=values)
    except Exception as exc:
        result.update(status='error', error_code=type(exc).__name__)
    return result


def persist_evaluation(db, result: dict[str, Any], *, decision_id: str | None, tenant_id: str) -> None:
    """Use the caller's transaction; persistence errors must remain visible."""
    from sqlalchemy import text
    if not tenant_id:
        raise ValueError('evaluation_tenant_required')
    db.execute(text('''INSERT INTO ragas_eval_results
        (eval_id, decision_log_id, tenant_id, evaluation_status, faithfulness, answer_relevance,
         context_precision, context_recall, evaluator_model, created_at, metadata_json)
        VALUES (:id, :decision, :tenant, :status, :faithfulness, :answer_relevance,
                :context_precision, :context_recall, :model, :created, :metadata)'''),
        {'id': result['eval_id'], 'decision': decision_id, 'tenant': tenant_id,
         'status': result['status'], **result['metrics'], 'model': CONTRACT_VERSION,
         'created': result['evaluated_at'],
         'metadata': json.dumps({k: v for k, v in result.items() if k != 'metrics'})})
