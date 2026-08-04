"""MAESTRO boundaries on all consequential agents (supplier / fraud / ranking).

The supplier-comms agent previously had NO boundary at all; fraud + ranking had boundaries defined
but never enforced at their call sites. This verifies the boundary exists, record_agent_action
validates+audits, and the supplier send path runs the boundary check (defense in depth before the
execution gate).
"""
from __future__ import annotations

from types import SimpleNamespace

from src.app.security.maestro_boundaries import (
    AGENT_BOUNDARIES,
    record_agent_action,
    validate_agent_action,
)


# ── boundary registry ──
def test_supplier_comms_boundary_now_defined():
    b = AGENT_BOUNDARIES.get("Supplier_Communication_Agent")
    assert b is not None and b.risk_tier == "high"
    assert "dispatch_supplier_message" in b.allowed_tools
    assert "suppliers" in b.allowed_data_scopes
    assert b.max_autonomous_value_usd == 0.0  # cannot auto-approve spend


def test_consequential_agents_all_have_boundaries():
    for name in ("Supplier_Communication_Agent", "Fraud_Scoring_Agent", "Product_Ranking_Agent", "Orchestrator"):
        assert name in AGENT_BOUNDARIES, f"missing MAESTRO boundary: {name}"


# ── record_agent_action ──
def test_record_agent_action_clean_pass_logs_nothing():
    logs = []
    v = record_agent_action(agent_name="Fraud_Scoring_Agent", tool_name="score_fraud",
                            data_scope="orders", log_fn=lambda **kw: logs.append(kw))
    assert v == [] and logs == []  # in-boundary -> no violation, no log


def test_record_agent_action_out_of_scope_tool_audits():
    logs = []
    v = record_agent_action(agent_name="Product_Ranking_Agent", tool_name="send_email",
                            data_scope="products", trace_id="t", log_fn=lambda **kw: logs.append(kw))
    assert any(x.violation_type == "tool_misuse" for x in v)
    assert logs and logs[0]["event_type"] == "maestro_boundary"
    assert logs[0]["payload"]["maestro_checked"] is True


def test_supplier_send_path_runs_boundary_check():
    from src.app.services.supplier_communication import draft_supplier_message, dispatch_supplier_message
    seen = {}

    def _boundary(**kw):
        seen.update(kw)
        return []  # clean

    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com", item="W")
    out = dispatch_supplier_message(
        draft=d, allow_send=True, boundary_check_fn=_boundary,
        decide_fn=lambda *a, **k: SimpleNamespace(allowed=True, decision=SimpleNamespace(value="allow"), reason="ok"),
        domain_trusted_fn=lambda e: True,
        mailer=SimpleNamespace(send=lambda **k: {"ok": True, "status": "sent"}),
    )
    # the boundary check ran for the supplier agent's dispatch tool before sending
    assert seen.get("agent_name") == "Supplier_Communication_Agent"
    assert seen.get("tool_name") == "dispatch_supplier_message" and seen.get("data_scope") == "suppliers"
    assert out["sent"] is True


def test_supplier_send_held_when_boundary_blocks():
    from src.app.services.supplier_communication import draft_supplier_message, dispatch_supplier_message
    from src.app.security.maestro_boundaries import MaestroViolationError, BoundaryViolation

    def _blocking(**kw):
        raise MaestroViolationError([BoundaryViolation("Supplier_Communication_Agent", "value_exceeded", "over limit", "critical")])

    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com", item="W")
    out = dispatch_supplier_message(draft=d, allow_send=True, boundary_check_fn=_blocking,
                                    mailer=SimpleNamespace(send=lambda **k: {"ok": True}))
    assert out["sent"] is False and out["status"] == "held_for_review"
    assert out["maestro"]["blocked"] is True
