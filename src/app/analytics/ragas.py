from __future__ import annotations

import time
import uuid
from typing import Any, Dict


def evaluate_decision_stub(proposal: Dict[str, Any], retrieved_context: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a decision using the RAGAS framework if available, else degrade gracefully."""
    eval_id = str(uuid.uuid4())
    metrics: Dict[str, Any] = {
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "context_recall": None,
    }
    evaluator_model = "unavailable"

    try:
        from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall  # type: ignore[import]
        from ragas import evaluate as ragas_evaluate  # type: ignore[import]
        from datasets import Dataset  # type: ignore[import]

        question = str(proposal.get("question") or proposal.get("proposed_action") or "")
        answer = str(proposal.get("answer") or proposal.get("reasoning") or "")
        contexts = retrieved_context.get("chunks") or retrieved_context.get("context_chunks") or []
        if isinstance(contexts, str):
            contexts = [contexts]
        ground_truth = str(retrieved_context.get("ground_truth") or "")

        if question and answer and contexts:
            ds = Dataset.from_dict({
                "question": [question],
                "answer": [answer],
                "contexts": [contexts],
                "ground_truth": [ground_truth],
            })
            result = ragas_evaluate(ds, metrics=[faithfulness, answer_relevancy, context_precision, context_recall])
            row = result.to_pandas().iloc[0]
            metrics["faithfulness"] = float(row.get("faithfulness", 0) or 0)
            metrics["answer_relevance"] = float(row.get("answer_relevancy", 0) or 0)
            metrics["context_precision"] = float(row.get("context_precision", 0) or 0)
            metrics["context_recall"] = float(row.get("context_recall", 0) or 0)
            evaluator_model = "ragas"
    except ImportError:
        # ragas or datasets not installed — skip evaluation, do not crash the decision pipeline
        pass
    except Exception:
        pass

    return {
        "eval_id": eval_id,
        "decision_mode": proposal.get("decision_mode", "agent"),
        "metrics": metrics,
        "evaluator_model": evaluator_model,
        "evaluated_at": int(time.time()),
    }


def persist_ragas_eval(db, ragas_payload: Dict[str, Any]) -> None:
    """Persist RAGAS evaluation results — best-effort, silent on missing table."""
    eval_id = ragas_payload.get("eval_id") or str(uuid.uuid4())
    try:
        metrics = ragas_payload.get("metrics", {}) if isinstance(ragas_payload.get("metrics"), dict) else {}
        evaluated_at = int(ragas_payload.get("evaluated_at", int(time.time())) or int(time.time()))
        db.execute(
            """
            INSERT INTO ragas_eval_results (eval_id, decision_log_id, faithfulness, answer_relevance, context_precision, context_recall, evaluated_at, evaluator_model)
            VALUES (:eval_id, :decision_log_id, :faithfulness, :answer_relevance, :context_precision, :context_recall, :evaluated_at, :evaluator_model)
            """,
            {
                "eval_id": eval_id,
                "decision_log_id": ragas_payload.get("decision_log_id"),
                "faithfulness": metrics.get("faithfulness"),
                "answer_relevance": metrics.get("answer_relevance"),
                "context_precision": metrics.get("context_precision"),
                "context_recall": metrics.get("context_recall"),
                "evaluated_at": evaluated_at,
                "evaluator_model": ragas_payload.get("evaluator_model", "unavailable"),
            },
        )
    except Exception:
        pass


# Backwards-compat alias
persist_ragas_stub = persist_ragas_eval
