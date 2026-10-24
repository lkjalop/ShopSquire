"""Compatibility adapters to the canonical evaluator and persistence contract."""
from __future__ import annotations
from typing import Any
from src.app.services.evaluation_contract import evaluate_sample, persist_evaluation
from src.app.platform.tenant_context import current_tenant_id


def evaluate_decision_stub(proposal: dict[str, Any], retrieved_context: dict[str, Any]) -> dict[str, Any]:
    return {**evaluate_sample(proposal.get('question') or proposal.get('proposed_action'),
                              retrieved_context, proposal.get('answer') or proposal.get('reasoning')),
            'decision_mode': proposal.get('decision_mode', 'agent')}


def persist_ragas_eval(db, ragas_payload: dict[str, Any]) -> None:
    persist_evaluation(db, ragas_payload, decision_id=ragas_payload.get('decision_log_id'), tenant_id=current_tenant_id())


persist_ragas_stub = persist_ragas_eval
