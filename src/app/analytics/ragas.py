from __future__ import annotations

import time
import uuid
from typing import Any, Dict


def evaluate_decision_stub(proposal: Dict[str, Any], retrieved_context: Dict[str, Any]) -> Dict[str, Any]:
    # Placeholder for future RAGAS evaluation pipeline.
    return {
        "eval_id": None,
        "decision_mode": proposal.get("decision_mode", "agent"),
        "metrics": {
            "faithfulness": None,
            "answer_relevance": None,
            "context_precision": None,
            "context_recall": None,
        },
        "evaluated_at": int(time.time()),
    }


def persist_ragas_stub(db, ragas_payload: Dict[str, Any]) -> None:
    # Best-effort insert into ragas_eval_results table if present.
    eval_id = ragas_payload.get("eval_id") or str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO ragas_eval_results (eval_id, decision_log_id, faithfulness, answer_relevance, context_precision, context_recall, evaluated_at, evaluator_model)
        VALUES (:eval_id, :decision_log_id, :faithfulness, :answer_relevance, :context_precision, :context_recall, to_timestamp(:evaluated_at), :evaluator_model)
        """,
        {
            "eval_id": eval_id,
            "decision_log_id": None,
            "faithfulness": ragas_payload.get("metrics", {}).get("faithfulness"),
            "answer_relevance": ragas_payload.get("metrics", {}).get("answer_relevance"),
            "context_precision": ragas_payload.get("metrics", {}).get("context_precision"),
            "context_recall": ragas_payload.get("metrics", {}).get("context_recall"),
            "evaluated_at": ragas_payload.get("evaluated_at", int(time.time())),
            "evaluator_model": "stub",
        },
    )
