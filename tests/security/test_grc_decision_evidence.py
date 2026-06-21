"""ISO 42001 / EU AI Act / PCI Req 10 / OWASP Agentic — decision-evidence pack (B4 cash-in).

Proves the framework-tagged audit (written by execution_gate B4) aggregates into procurement-ready
evidence: counts of consequential decisions, the decision split, and the breakdown by OWASP-Agentic
ASI tag / action / compliance framework.
"""
from __future__ import annotations

from src.app.policy.execution_gate import decide
from src.app.routers.admin_grc import build_decision_evidence


def test_evidence_aggregates_framework_tagged_decisions():
    # Seed real audit rows through the gate (this is the B4 -> evidence integration).
    decide("refund", value_cents=4000, actor="agent:test", tenant_id="t1")
    decide("bank_change", value_cents=0, actor="agent:test", tenant_id="t1")

    ev = build_decision_evidence(days=1, limit=50)
    assert ev["total_consequential_decisions"] >= 2
    assert ev["audit_coverage"]["queryable"] is True
    assert ev["audit_coverage"]["framework_tagged_rows"] >= 2

    # ASI02 is stamped on every consequential action; bank_change adds a higher-risk tag.
    assert "ASI02:ToolMisuse" in ev["by_owasp_agentic_tag"]
    assert any(t.startswith("ASI09") or t.startswith("ASI03") for t in ev["by_owasp_agentic_tag"])

    assert "refund" in ev["by_action"] and "bank_change" in ev["by_action"]
    assert "pci_dss_req10_audit_trail" in ev["compliance_frameworks"]
    assert "iso_42001_decision_logging" in ev["compliance_frameworks"]

    assert ev["recent"], "recent examples must be present"
    assert "owasp_agentic" in ev["recent"][0] and "decision" in ev["recent"][0]


def test_decision_split_present():
    decide("refund", value_cents=100_000)  # high-value -> human_review
    ev = build_decision_evidence(days=1, limit=10)
    # at least one decision bucket recorded
    assert sum(ev["by_decision"].values()) == ev["total_consequential_decisions"] >= 1


def test_empty_window_is_queryable_not_error():
    ev = build_decision_evidence(days=1, limit=5)
    assert isinstance(ev["by_action"], dict)
    assert ev["audit_coverage"]["queryable"] is True  # no rows is still a valid (queryable) state
