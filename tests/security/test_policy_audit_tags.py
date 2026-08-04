"""B4 — every consequential decision is audited with framework tags (PCI Req10 / ISO 42001 / OWASP Agentic).

The execution gate and the legacy route_enforcement seam must BOTH write a canonical
policy_evaluation_log row carrying OWASP-Agentic ASI tags, so the audit trail is queryable by
framework. enforce_action_authority previously logged only via the shadow engine (control-plane,
can no-op on schema drift); now it reliably records the AUTHORITATIVE verdict.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import inspect, text

from src.app.models.db import db_session
from src.app.policy.action_authority_matrix import AuthDecision
from src.app.policy.execution_gate import decide, framework_tags, record_policy_decision
from src.app.policy.route_enforcement import enforce_action_authority


def _latest_context(action: str) -> dict:
    with db_session() as db:
        columns = {
            str(column["name"])
            for column in inspect(db.get_bind()).get_columns("policy_evaluation_log")
        }
        context_column = "context" if "context" in columns else "guardrails_json"
        canonical_filter = (
            "AND policy_version = 'execution_gate_matrix_v1'"
            if "policy_version" in columns
            else ""
        )
        row = db.execute(
            text(
                f"SELECT {context_column} FROM policy_evaluation_log "
                f"WHERE action = :a {canonical_filter} "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"a": action},
        ).scalar()
    if not row:
        return {}
    try:
        return json.loads(row)
    except Exception:
        return {}


def _count(action: str) -> int:
    with db_session() as db:
        columns = {
            str(column["name"])
            for column in inspect(db.get_bind()).get_columns("policy_evaluation_log")
        }
        canonical_filter = (
            "AND policy_version = 'execution_gate_matrix_v1'"
            if "policy_version" in columns
            else ""
        )
        return int(
            db.execute(
                text(
                    "SELECT COUNT(*) FROM policy_evaluation_log "
                    f"WHERE action = :a {canonical_filter}"
                ),
                {"a": action},
            ).scalar()
            or 0
        )


# ── framework_tags ──
def test_framework_tags_every_action_carries_tool_misuse():
    t = framework_tags("refund")
    assert "ASI02:ToolMisuse" in t["owasp_agentic_top10"]
    assert t["control"] == "execution_gate"
    assert "pci_dss_req10_audit_trail" in t["compliance"]
    assert "iso_42001_decision_logging" in t["compliance"]


def test_framework_tags_high_risk_actions_add_specific_tags():
    assert "ASI09:HumanAgentTrustExploitation" in framework_tags("bank_change")["owasp_agentic_top10"]
    assert "ASI03:IdentityPrivilegeAbuse" in framework_tags("bank_change")["owasp_agentic_top10"]
    assert "ASI04:AgenticSupplyChainVulnerabilities" in framework_tags("supplier_add")["owasp_agentic_top10"]
    assert "ASI03:IdentityPrivilegeAbuse" in framework_tags("pii_export")["owasp_agentic_top10"]


# ── decide() stamps tags into the audit row ──
def test_decide_writes_framework_tags_to_audit_row():
    decide("refund", value_cents=4000, actor="agent:test", tenant_id="t1")
    ctx = _latest_context("refund")
    fw = ctx.get("frameworks") or {}
    assert "ASI02:ToolMisuse" in (fw.get("owasp_agentic_top10") or [])
    assert fw.get("control") == "execution_gate"


# ── enforce_action_authority now reliably audits the AUTHORITATIVE verdict ──
def test_enforce_allow_writes_canonical_audit_row():
    action = "refund"
    before = _count(action)
    v = enforce_action_authority(action, value_aud_cents=4000, context={"requested_by_role": "merchant", "tenant_id": "t1"})  # <= $50 -> ALLOW
    assert v.decision == AuthDecision.ALLOW
    assert _count(action) == before + 1  # exactly one row written for the enforced verdict
    fw = (_latest_context(action).get("frameworks") or {})
    assert "ASI02:ToolMisuse" in (fw.get("owasp_agentic_top10") or [])


def test_enforce_deny_still_audits_then_raises():
    from fastapi import HTTPException
    action = "refund"
    before = _count(action)
    with pytest.raises(HTTPException):
        enforce_action_authority(action, value_aud_cents=100_000, context={"requested_by_role": "merchant"})  # > $500 -> HUMAN_REVIEW -> 409
    assert _count(action) == before + 1  # audited BEFORE the raise (no consequential action unlogged)


# ── record_policy_decision ──
def test_record_policy_decision_stamps_and_logs():
    from src.app.policy.action_authority_matrix import PolicyVerdict
    action = "supplier_pay"
    before = _count(action)
    v = PolicyVerdict(decision=AuthDecision.DUAL_CONTROL, reason="test", rule_id="X", context={})
    record_policy_decision(action, 50_000, v, tenant_id="t1", actor="agent:test", seam="unit")
    assert _count(action) == before + 1
    assert v.context["seam"] == "unit"
    assert "ASI09:HumanAgentTrustExploitation" in v.context["frameworks"]["owasp_agentic_top10"]
