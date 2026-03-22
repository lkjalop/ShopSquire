from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.security.email_security import evaluate_email_security
from src.app.security.supplier_governance_store import update_supplier_governance_snapshot


def _seed_governance() -> None:
    update_supplier_governance_snapshot(
        tenant_id="tenant-admin-governance",
        email={
            "from_addr": "accounts@ingramfake.com.au",
            "reply_to": "accounts@ingramfake.com.au",
            "vendor_domain": "ingramtech.com.au",
            "attachments": [{"name": "fake.pdf", "template_hash": "tmpl-bad"}],
        },
        evidence_snapshot={
            "attachment_forensics": [
                {"file_name": "fake.pdf", "extracted_bank_fingerprint": "bank-fp-admin", "evidence_excerpt_lines": []}
            ],
            "artifact_intel": {"baseline_checks": {"vendor_domain": "ingramtech.com.au", "vendor_name": "IngramTech"}},
        },
        structured_findings=[{"finding_type": "payment_change_request", "confidence_band": "high"}],
    )


def test_admin_supplier_governance_review_endpoint():
    _seed_governance()
    client = TestClient(create_app())

    dashboard = client.get(
        "/api/v1/admin/email_security/supplier-governance?tenant_id=tenant-admin-governance",
        headers={"x-api-key": "local-owner-key"},
    )
    assert dashboard.status_code == 200, dashboard.text
    items = (dashboard.json() or {}).get("items") or []
    assert items
    row = next(i for i in items if i.get("supplier_key") == "ingramtech.com.au")
    pending = row.get("pending_updates") or []
    assert pending

    review = client.post(
        "/api/v1/admin/email_security/supplier-governance/review",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-admin-governance",
            "supplier_key": "ingramtech.com.au",
            "update_key": pending[0],
            "decision": "approve",
            "actor_id": "tester",
            "actor_role": "owner",
        },
    )
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["ok"] is True
    assert pending[0] not in ((body.get("profile") or {}).get("pending_updates") or [])


def test_admin_incident_graph_endpoint_returns_timeline_and_relationships():
    evaluate_email_security(
        {
            "message_id": "<graph-admin-1@x>",
            "from_addr": "accounts@ingramfake.com.au",
            "reply_to": "accounts@payments-ingramfake.net",
            "subject": "Updated payment details",
            "body": "Please use the new account immediately.",
            "vendor_domain": "ingramtech.com.au",
            "attachments": [
                {
                    "name": "IngramFake_March2026_Catalog.pdf",
                    "content_type": "application/pdf",
                    "extracted_text": "Banking details have changed. BSB 062-111 Account 12345678",
                    "sha256": "d" * 64,
                    "template_hash": "tmpl-graph-bad",
                }
            ],
        },
        tenant_id="tenant-admin-graph",
    )

    client = TestClient(create_app())
    listing = client.get("/api/v1/admin/email_security/incidents", headers={"x-api-key": "local-owner-key"})
    assert listing.status_code == 200, listing.text
    incidents = [
        row
        for row in ((listing.json() or {}).get("incidents") or [])
        if row.get("tenant_id") == "tenant-admin-graph"
    ]
    assert incidents
    incident_id = str(incidents[0]["id"])

    graph = client.get(
        f"/api/v1/admin/email_security/incidents/{incident_id}/graph",
        headers={"x-api-key": "local-owner-key"},
    )
    assert graph.status_code == 200, graph.text
    body = graph.json()
    assert body["incident_id"] == incident_id
    incident_graph = body.get("incident_graph") or {}
    assert isinstance(incident_graph.get("timeline"), list)
    relationships = incident_graph.get("relationships") or {}
    assert isinstance(relationships.get("domains"), list)
    assert isinstance(relationships.get("bank_fingerprints"), list)
    assert isinstance(relationships.get("template_hashes"), list)
    vendor_graph = body.get("vendor_trust_graph") or {}
    assert isinstance(vendor_graph.get("timeline"), list)
    governance = body.get("supplier_governance") or {}
    assert governance.get("supplier_key") == "ingramtech.com.au"
