"""OKF export: a procurement case renders as a conformant OKF v0.1 document (markdown + YAML frontmatter)
with the required `type` field and the decision artifact (buyer need, RFQ, evidence, RFI, journey)."""
from __future__ import annotations

from src.app.services.fulfillment.okf_export import case_to_okf

_STATE = {
    "availability": {"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0, "shortfall": 7},
    "requirements": {"use_case": "office", "specs": ["16gb ram"], "needed_within_days": 14},
    "draft": {"subject": "Availability and quote request - GAM-0002 x 7",
              "body": "Hello.\n\nThis request does not constitute a purchase order.",
              "content_hash": "abc123def456abc1def", "recipient_domain": "approved-supplier.example",
              "recipient_email": "orders@approved-supplier.example",
              "commercial_scope": {"item_ref": "GAM-0002", "quantity": 7},
              "send_gate": {"decision": "allow"},
              "evidence": [{"evidence_id": "INV-1", "source": "inventory", "summary": "shortfall 7 of 7"}]},
}
_JOURNEY = [
    {"event": "availability_assessed", "state": "AVAILABILITY_ASSESSED", "actor_type": "agent",
     "reason_code": "bulk_shortfall", "valid_from": "2026-06-27 09:00:01"},
    {"event": "buyer_committed", "state": "COMMITTED", "actor_type": "buyer", "valid_from": "2026-06-27 09:05:00"},
]


def test_case_to_okf_has_conformant_frontmatter():
    md = case_to_okf(case_id="fc-12345678", state="AWAITING_APPROVAL", state_json=_STATE,
                     journey=_JOURNEY, timestamp="2026-06-27 09:06:00")
    # OKF v0.1: a markdown doc opening with YAML frontmatter; `type` is the only REQUIRED field.
    assert md.startswith("---\n")
    head = md.split("---", 2)[1]
    assert "type: ProcurementCase" in head
    for field in ("title:", "description:", "resource:", "tags:", "timestamp:"):
        assert field in head
    assert "resource: /api/v1/fulfillment/cases/fc-12345678" in head


def test_case_to_okf_includes_decision_artifact():
    md = case_to_okf(case_id="fc-12345678", state="AWAITING_APPROVAL", state_json=_STATE, journey=_JOURNEY)
    assert "## Buyer requirement" in md and "GAM-0002" in md and "Intended use: office" in md
    assert "## Supplier RFQ (draft)" in md and "approved-supplier.example" in md
    assert "Pre-send gate: allow" in md
    assert "### Evidence packet" in md and "INV-1" in md
    assert "## Decision journey (bitemporal)" in md and "buyer_committed" in md
    # the artifact carries the claim-safe draft body (no price/PO leak introduced)
    assert "does not constitute a purchase order" in md


def test_case_to_okf_is_robust_to_sparse_state():
    md = case_to_okf(case_id="fc-empty", state="NEW", state_json={}, journey=[])
    assert "type: ProcurementCase" in md and "# Procurement case fc-empty" in md
