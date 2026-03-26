from __future__ import annotations

import base64

from fastapi.testclient import TestClient


def test_homoglyph_sample_api_returns_lookalike_domain():
    from src.app.main import create_app

    client = TestClient(create_app())
    payload = {
        "tenant_id": "email-sec-regression",
        "message_id": "<homoglyph-api@x>",
        "from_addr": "CEO <ceo@micros0ft.com>",
        "reply_to": "finance@micros0ft.com",
        "subject": "Urgent payment reroute",
        "body": "Please update payment to https://micros0ft.com/payments immediately.",
        "attachments": [],
        "dmarc_fail": False,
        "vendor_domain": "microsoft.com",
    }
    r = client.post("/api/v1/email_security/evaluate", headers={"x-api-key": "local-developer-key"}, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("lookalike_domain"), dict)
    assert body["lookalike_domain"].get("detected") is True


def test_reference_material_does_not_escalate_to_error():
    from src.app.security.email_security import evaluate_email_security

    attachment_body = """# Detection Playbook Summary

This security training guide summarizes example fraud, QR invoice, payment diversion,
thread hijacking, and beaconing scenarios for analyst testing only.
"""
    out = evaluate_email_security(
        {
            "message_id": "<reference-doc@x>",
            "from_addr": "security.training@shopsquire.ai",
            "reply_to": "security.training@shopsquire.ai",
            "subject": "Detection Playbook Summary",
            "body": attachment_body,
            "attachments": [
                {
                    "name": "DETECTION_PLAYBOOK_SUMMARY.md",
                    "content_type": "text/markdown",
                    "content_b64": base64.b64encode(attachment_body.encode("utf-8")).decode("ascii"),
                }
            ],
            "dmarc_fail": False,
        },
        tenant_id="email-sec-reference",
    )
    assert out.get("content_mode") == "security_training_material"
    assert out.get("severity") != "error"
    assert out.get("route") == "auto_resolve"
    assert "reference_material_context" in (out.get("reasons") or [])


def test_pdf_qr_invoice_surfaces_qr_linked_indicators(monkeypatch):
    from src.app.security import email_attachment_parser as parser
    from src.app.security.email_security import evaluate_email_security

    class _FakeQRResult:
        codes = [
            {
                "data": "https://scanned.page/p/R2g2Jb",
                "type": "QR_CODE",
                "payload_type": "url",
                "is_external_url": True,
                "host": "scanned.page",
                "risk_level": "review",
                "risk_reason": "QR points to external host scanned.page.",
                "policy_action": "review",
                "is_benign_qr": False,
            }
        ]

    monkeypatch.setattr(parser, "_render_pdf_page_images", lambda *_args, **_kwargs: [b"fake-pdf-page"], raising=True)
    monkeypatch.setattr("src.app.rules.barcode_decode.decode_barcodes", lambda *_args, **_kwargs: _FakeQRResult(), raising=True)
    monkeypatch.setattr(
        "src.app.security.linked_artifact_analysis.analyze_linked_artifact",
        lambda **_kwargs: {
            "linked_artifact_available": True,
            "linked_artifact_type": "pdf",
            "linked_final_url": "https://scanned.page/p/R2g2Jb",
            "linked_attack_hypothesis": "linked_pii_exposure",
            "linked_owner_scope": "external",
            "linked_owner_reason": "fixture",
            "linked_exposure_scope": "public",
            "linked_breach_severity_hint": "high",
            "linked_human_verification_required": True,
            "linked_crisis_management_required": False,
            "linked_offline_fixture": True,
            "linked_offline_fixture_tag": "qr_invoice_pdf",
            "linked_reason_summary": "Linked PDF exposes SSN-like identity content.",
            "linked_policy_action": "review",
            "pii_detected": True,
            "pii_type": ["ssn"],
            "ssn_hits": ["123-45-6789"],
            "linked_text_excerpt": "SSN 123-45-6789",
        },
        raising=True,
    )

    out = evaluate_email_security(
        {
            "message_id": "<pdf-qr@x>",
            "from_addr": "supplier@example.com",
            "reply_to": "supplier@example.com",
            "subject": "Invoice PDF",
            "body": "Please review attached invoice.",
            "attachments": [
                {
                    "name": "TEST_PDF_01_QR_Code_Invoice.pdf",
                    "content_type": "application/pdf",
                    "content_b64": base64.b64encode(b"%PDF-1.7 fake").decode("ascii"),
                }
            ],
            "dmarc_fail": False,
        },
        tenant_id="email-sec-pdf-qr",
    )
    attachment_forensics = ((out.get("evidence_snapshot") or {}).get("attachment_forensics") or [])
    assert attachment_forensics
    first = attachment_forensics[0]
    assert first.get("qr_code_detected") is True
    assert first.get("qr_external_url_detected") is True
    assert "https://scanned.page/p/R2g2Jb" in (first.get("qr_payloads") or [])
    assert "Linked PDF exposes SSN-like identity content." in str(first.get("linked_reason_summary") or "")
    structured = ((out.get("evidence_snapshot") or {}).get("structured_findings") or [])
    assert any(str((row or {}).get("finding_type") or "") == "qr_redirect_risk" for row in structured)


def test_escalated_verdict_exposes_playbook_run():
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(
        {
            "message_id": "<playbook-visible@x>",
            "from_addr": "accounts@ingramfake.com.au",
            "reply_to": "accounts@ingramfake.com.au",
            "subject": "Updated remittance details",
            "body": "Urgent payment reroute. Please use the new account immediately.",
            "attachments": [],
            "dmarc_fail": True,
            "vendor_domain": "ingramtech.com.au",
        },
        tenant_id="email-sec-playbook",
    )
    assert out.get("route") in {"security_review", "human_review"}
    assert isinstance(out.get("playbook_run"), dict)
    assert out["playbook_run"].get("run_id") or out["playbook_run"].get("playbook_id")
