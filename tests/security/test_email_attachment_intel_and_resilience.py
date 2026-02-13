import os


def _patch_thresholds(monkeypatch):
    thresholds = {
        "SECURITY_THRESHOLDS": {
            "BEC_WARN_INDICATORS": 2,
            "BEC_ERROR_INDICATORS": 3,
            "IOC_WARN_COUNT": 1,
            "IOC_ERROR_COUNT": 2,
            "TRUSTED_VENDOR_DOMAINS": ["ingramfake.com.au"],
            "INTERNAL_EMAIL_DOMAINS": ["shopsquire.ai"],
            "TRUSTED_VENDOR_BASELINES": {
                "ingramfake.com.au": {
                    "abn": "13504561230",
                    "bank_fingerprint": "bank-old",
                    "approved_contacts": ["accounts@ingramfake.com.au"],
                    "approved_pos": ["PO-2025-0341"],
                    "approved_grns": ["GRN-1001"],
                    "approved_receipts": ["REC-1001"],
                }
            },
        },
        "TICKET_RATE_LIMIT": {"enabled": False, "per_min": 100},
    }
    import src.app.security.email_security as es
    import src.app.security.email_security_rules as rules
    import src.app.security.email_security_verdict as verdict
    monkeypatch.setattr(es, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(rules, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(verdict, "load_feature_flags", lambda *_args, **_kwargs: thresholds)


def test_attachment_intel_extracts_and_cross_checks(monkeypatch):
    _patch_thresholds(monkeypatch)
    from src.app.security.email_security import evaluate_email_security

    cyra = "\u0430"
    out = evaluate_email_security(
        {
            "message_id": "<att-intel@x>",
            "from_addr": f"George <accounts@ingramf{cyra}ke.com.au>",
            "reply_to": f"accounts@ingramf{cyra}ke.com.au",
            "subject": "TAX INVOICE INV-2026-00847",
            "body": "Please note our banking details have recently changed. Disregard any previous remittance instructions.",
            "vendor_domain": "ingramfake.com.au",
            "bank_fingerprint": "bank-old",
            "proposed_bank_fingerprint": "bank-new",
            "external_sender": True,
            "attachments": [
                {
                    "name": "invoice.pdf",
                    "extracted_text": (
                        "IngramFаke Pty Ltd\nABN: 13 504 561 230\nInvoice No. INV-2026-00847\n"
                        "Due Date: 27 February 2026\nTotal Amount Due: $47,272.50 AUD\n"
                        "BSB: 062-205\nAccount No.: 1049 3827\nPO-2025-9999\n"
                    ),
                    "template_hash": "tpl-new",
                    "expected_template_hash": "tpl-old",
                    "logo_hash": "logo-new",
                    "expected_logo_hash": "logo-old",
                    "edited_regions": 3,
                    "compression_artifact_score": 0.7,
                }
            ],
        },
        tenant_id="t-red",
    )
    artifact = ((out.get("evidence_snapshot") or {}).get("artifact_intel") or {})
    parsed = artifact.get("parsed_fields") or {}
    scores = artifact.get("signal_scores") or {}
    ind_types = {str(i.get("type")) for i in (out.get("indicators") or [])}
    assert parsed.get("invoice_number")
    assert "vendor_homoglyph_impersonation" in ind_types
    assert "template_drift" in ind_types
    assert "logo_layout_mismatch" in ind_types
    assert "edited_region_artifact" in ind_types
    assert scores.get("band") in ("review", "block")
    assert out.get("route") in ("human_review", "security_review")


def test_simhash_is_non_scoring_for_external_sender_only(monkeypatch):
    _patch_thresholds(monkeypatch)
    from src.app.security.email_security_verdict import verdict as compute_verdict

    out = compute_verdict(
        {"message_id": "<simhash-only@x>"},
        {"indicators": [{"type": "simhash_fingerprint", "value": "abc", "reason": "cluster"}], "iocs": [], "meta": {}},
        dmarc_fail=False,
    )
    # The key regression check: simhash remains present but does not increase scoring.
    assert "multi-signal threshold met" not in (out.get("reasons") or [])
    assert out.get("severity") == "info"
    assert out.get("route") == "auto_resolve"


def test_enrichment_and_detonation_failures_are_graceful(monkeypatch):
    _patch_thresholds(monkeypatch)
    import src.app.security.email_security as es

    monkeypatch.setattr(es, "enrich_iocs", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("enrichment_down")))
    monkeypatch.setattr(es, "detonate_targets", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("detonation_timeout")))
    out = es.evaluate_email_security(
        {
            "message_id": "<chaos-email@x>",
            "from_addr": "ops@supplier.com",
            "reply_to": "ops@supplier.com",
            "subject": "Stock update",
            "body": "No urgent action required.",
            "attachments": [],
        },
        tenant_id="t-chaos",
    )
    assert out.get("severity") in ("info", "warning", "error")
    reasons = out.get("reasons") or []
    assert "ioc_enrichment_unavailable" in reasons
    assert "sandbox_detonation_unavailable" in reasons
