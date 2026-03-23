from fastapi.testclient import TestClient

from src.app.main import create_app


def test_email_lab_html_keeps_js_escape_sequences_and_playbook_panel():
    client = TestClient(create_app())

    response = client.get("/merchant/email-lab", headers={"host": "127.0.0.1:8080"})

    assert response.status_code == 200
    html = response.text

    assert 'id="playbook_card"' in html
    assert 'id="exec_card"' in html
    assert 'id="evidence_card"' in html
    assert 'id="actions_card"' in html
    assert 'id="integrations_card"' in html
    assert 'id="gov_card"' in html
    assert 'id="graph_card"' in html
    assert 'id="infra_card"' in html
    assert 'id="tones_card"' in html
    assert 'id="pdf_diff_card"' in html
    assert 'id="visual_diff_card"' in html
    assert 'id="trace_human"' in html
    assert "toggleDetachRightRail()" in html
    assert "openRightRailTab()" in html
    assert "replaySiemHandoff()" in html
    assert "renderExecutiveSummary(j);" in html
    assert "renderInfrastructureSummary(j);" in html
    assert "renderSupplierGovernance(j);" in html
    assert "renderVendorTrustGraph(j);" in html
    assert "reviewSupplierGovernance(updateKey, decision)" in html
    assert "Incident Timeline" in html
    assert "Relationship Buckets" in html
    assert "What Triggered It" in html
    assert "What Agents Found" in html
    assert "Threat Hunter Leads" in html
    assert "Direct:</strong>" in html
    assert "Inferred:</strong>" in html
    assert "Context only:</strong>" in html
    assert "Do This Now" in html
    assert "Governance / Trust" in html
    assert "Audit / Compliance" in html
    assert "Notifications / Push" in html
    assert "Plain-English triggers" in html
    assert "Trust degraded" in html
    assert "Audit mapping available" in html
    assert "Attachment detail" in html
    assert "Open related incident detail" in html
    assert "Open governance and trust detail" in html
    assert "Open trust graph detail" in html
    assert "Open raw and explain trace" in html
    assert "Open audit mapping" in html
    assert "Open sandbox and IOC detail" in html
    assert "Push Recommendation" in html
    assert "Target-specific hunt checklist" in html
    assert "Push to SIEM/XDR now" in html
    assert "Already pushed" in html
    assert "Hold push until human review" in html
    assert "Push to Proofpoint/Mimecast recommended" in html
    assert "Threat hunter leads" in html
    assert "Connector registry and delivery history" in html
    assert "Connector Registry" in html
    assert "Delivery History" in html
    assert "renderVerdictTones(j);" in html
    assert "renderAttachmentForensics(ev);" in html
    assert "renderPdfBaselineDiff(ev);" in html
    assert "renderVisualBaselineDiff(ev);" in html
    assert "findingToPlainEnglish(f)" in html
    assert "findingProvenanceChips(f)" in html
    assert "findingDrilldownHtml(f)" in html
    assert "ownerScopeBadgeHtml(scope)" in html
    assert "Owner: internal" in html
    assert "Owner: external" in html
    assert "Owner: redirect / unknown" in html
    assert "attachmentProvenanceChips(item)" in html
    assert "provenanceChipLabel(src)" in html
    assert "Top Ranked Evidence" in html
    assert "Agent audit" in html
    assert "Human Gate Thresholds" in html
    assert "Refresh Connector Health" in html
    assert "Mark Legit" in html
    assert "Request Baseline Update" in html
    assert "Pending Approvals" in html
    assert ">Approve</button>" in html
    assert ">Reject</button>" in html
    assert "<details class=\"finding-drilldown\">" in html
    assert 'alt="pdf overlay preview"' in html
    assert 'alt="pdf heatmap preview"' in html
    assert "submitFeedbackOutcome(" in html
    assert "refreshConnectorHealth()" in html
    assert "textContent = out.join('\\\\n')" in html
    assert "textContent = list.join('\\\\n')" in html
    assert "INVOICE #INV-2026-0142\\\\nIngramWake Pty Ltd" in html
    assert "accounts@ingramf\\u0430ke.com.au\\\\nSubject: Updated Payment Details" in html
    assert "IngramWake March 2026 Catalog\\\\nProduct Ref: IW-CAT-2026-03" in html
    assert "out.join('\n')" not in html
    assert "list.join('\n')" not in html


def test_email_security_replay_event_endpoint_accepts_normalized_event():
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/admin/email_security/connectors/replay-event",
        headers={"x-api-key": "local-owner-key"},
        json={
            "event": {
                "schema_version": "shopsquire.security.v1",
                "event_time": 1,
                "source": "email_security_agent",
                "tenant_id": "test-tenant",
                "decision_id": "dec-1",
                "trace_id": "dec-1",
                "entity": {"message_id_hash": "abc"},
                "verdict": {"severity": "warning", "action": "security_review", "route": "security_review", "escalation": "security_middleware", "risk_band": "high"},
                "reasons": ["artifact_risk_block_band"],
                "tags": ["email_security"],
                "ioc": {},
                "evidence": {},
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "result" in body
