import json

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.decision_log import log_decision


def test_log_decision_enforces_evidence_verifier_and_abstain(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/decision_quality.sqlite")
    monkeypatch.setenv("DECISION_VERIFIER_STRICT", "1")
    monkeypatch.setenv("DECISION_ABSTAIN_THRESHOLD", "0.45")

    dec_id = log_decision(
        agent_name="recommendation_agent",
        input_data={"uid_hash": "u1", "query": "test"},
        retrieved_context={},
        proposed_action={"confidence": 0.1, "action": "approve"},
        policy_version="v1",
        execution_status="executed",
        approval_required=False,
    )
    assert dec_id

    with db_session() as db:
        row = db.execute(
            text(
                "SELECT proposed_action, retrieved_context, execution_status, approval_required "
                "FROM decision_logs WHERE id = :id"
            ),
            {"id": dec_id},
        ).fetchone()

    assert row is not None
    action = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
    ctx = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})

    assert isinstance(action.get("evidence_items"), list)
    assert isinstance(action.get("evidence_weighting"), dict)
    assert "counterfactual" in action
    assert action.get("abstained") is True
    assert action.get("confidence_calibrated") <= 0.45
    assert isinstance(ctx.get("verifier_chain"), list)
    assert row[2] == "review_required"
    assert bool(row[3]) is True
