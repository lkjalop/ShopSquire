"""Execution gate (P3) — the single decide-and-log entry for consequential actions.

This is the control-layer eval (P4 seed): it proves the moat invariant — the gate
decides correctly AND there is no consequential action without a logged verdict.
"""
from __future__ import annotations

from sqlalchemy import text

from src.app.policy.execution_gate import decide, is_consequential
from src.app.policy.action_authority_matrix import AuthDecision
from src.app.models.db import db_session


def _policy_log_count_for(action: str) -> int:
    with db_session() as db:
        return int(db.execute(
            text("SELECT COUNT(*) FROM policy_evaluation_log WHERE action = :a"), {"a": action}
        ).scalar() or 0)


def test_unmapped_action_fails_closed():
    v = decide("totally_unknown_consequential_action_zzz", value_cents=999_00)
    assert v.decision != AuthDecision.ALLOW
    assert v.decision == AuthDecision.HUMAN_REVIEW  # matrix default, not ALLOW


def test_every_decision_is_logged():
    # The moat guarantee: no consequential action without a logged verdict.
    action = "refund_gate_logtest"
    before = _policy_log_count_for(action)
    decide(action, value_cents=5000, actor="agent:test", tenant_id="t1")
    after = _policy_log_count_for(action)
    assert after == before + 1, "decide() must write exactly one policy_evaluation_log row"


def test_mapped_action_evaluated_by_matrix():
    v = decide("refund", value_cents=5000)
    # a real rule governs it (not the fail-closed default)
    assert v.rule_id not in ("DEFAULT_FAIL_CLOSED", "GATE_ERROR")


def test_consequential_set_covers_money_actions():
    for a in ("refund", "supplier_pay", "bank_change", "discount", "pii_export"):
        assert is_consequential(a)
    assert not is_consequential("show_products")


def test_decide_never_raises_on_bad_input():
    v = decide(None)  # type: ignore
    assert v.decision != AuthDecision.ALLOW
