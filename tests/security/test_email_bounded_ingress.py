from src.app.security import email_security


def test_bounded_ingress_skips_deep_network_and_attachment_enrichment(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("deep enrichment ran on bounded ingress")

    monkeypatch.setattr(email_security, "hydrate_attachments_from_bytes", forbidden)
    monkeypatch.setattr(email_security, "sanitize_attachment_ocr_for_llm", forbidden)
    monkeypatch.setattr(email_security, "analyze_email_artifacts", forbidden)
    monkeypatch.setattr(email_security, "run_dns_auth_checks_parallel", forbidden)
    monkeypatch.setattr(email_security, "enrich_iocs", forbidden)
    monkeypatch.setattr(email_security, "detonate_targets", forbidden)
    monkeypatch.setattr(email_security, "analyze_phishing_targets", forbidden)
    monkeypatch.setattr(email_security, "_llm_assist_summary", forbidden)

    verdict = email_security.evaluate_email_security(
        {
            "message_id": "bounded-1",
            "from_addr": "quotes@approved-supplier.example",
            "reply_to": "quotes@approved-supplier.example",
            "subject": "Quote response",
            "body": "Six units at AUD 100 each.",
            "attachments": [],
            "spf_result": "pass",
            "dkim_result": "pass",
            "dmarc_result": "pass",
        },
        tenant_id="tenant-a",
        bounded_ingress=True,
    )
    assert verdict["evidence_snapshot"]["load_shed"]["fast_path_only"] is True
