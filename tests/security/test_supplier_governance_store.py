from __future__ import annotations

from src.app.security.supplier_governance_store import (
    get_supplier_governance_profile,
    review_supplier_governance_update,
    update_supplier_governance_snapshot,
)


def test_supplier_governance_review_moves_pending_update_to_approved_domain():
    email = {
        "from_addr": "accounts@ingramfake.com.au",
        "reply_to": "accounts@ingramfake.com.au",
        "vendor_domain": "ingramtech.com.au",
        "attachments": [
            {
                "name": "fake.pdf",
                "template_hash": "tmpl-bad",
                "layout_hash": "layout-bad",
                "logo_hash": "logo-bad",
            }
        ],
    }
    evidence_snapshot = {
        "attachment_forensics": [
            {
                "file_name": "fake.pdf",
                "extracted_bank_fingerprint": "bank-fp-1",
                "evidence_excerpt_lines": ["accounts@ingramfake.com.au"],
            }
        ],
        "artifact_intel": {
            "baseline_checks": {"vendor_domain": "ingramtech.com.au", "vendor_name": "IngramTech"},
            "parsed_fields": {"vendor_name": "IngramTech"},
        },
    }
    findings = [{"finding_type": "payment_change_request", "confidence_band": "high"}]

    snapshot = update_supplier_governance_snapshot(
        tenant_id="tenant-governance-test",
        email=email,
        evidence_snapshot=evidence_snapshot,
        structured_findings=findings,
    )
    assert any(x.startswith("review_domain:ingramfake.com.au") for x in (snapshot.get("pending_updates") or []))

    target = next(x for x in snapshot["pending_updates"] if x.startswith("review_domain:ingramfake.com.au"))
    out = review_supplier_governance_update(
        tenant_id="tenant-governance-test",
        supplier_key="ingramtech.com.au",
        update_key=target,
        decision="approve",
        actor_id="tester",
        actor_role="owner",
        note="approved trusted finance alias",
    )
    assert out["ok"] is True
    profile = get_supplier_governance_profile(tenant_id="tenant-governance-test", supplier_key="ingramtech.com.au")
    assert "ingramfake.com.au" in (profile.get("approved_domains") or [])
    assert target not in (profile.get("pending_updates") or [])
    assert any("approve:" in x for x in (profile.get("history") or []))
