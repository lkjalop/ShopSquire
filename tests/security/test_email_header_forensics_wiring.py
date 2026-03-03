from __future__ import annotations


def test_email_header_forensics_detects_timing_and_messageid_reuse(monkeypatch):
    import src.app.security.email_header_forensics as hf

    # Reset cache for deterministic test.
    hf._MSGID_CACHE.clear()  # type: ignore[attr-defined]

    email = {
        "from_addr": "billing@supplier.com",
        "message_id": "<dup-1@evil-payments.example>",
        "received_headers": [
            "from smtp1.example [203.0.113.55] by mx.example; Thu, 06 Mar 2026 10:00:00 +0000",
            "from smtp2.example [203.0.113.56] by mx2.example; Thu, 06 Mar 2026 11:00:00 +0000",
        ],
        "x_originating_ip": "203.0.113.55",
        "x_mailer": "Python-Requests/2.31",
    }

    first = hf.analyze_email_headers(email)
    second = hf.analyze_email_headers(email)

    assert bool(first.get("timing_anomaly")) is True
    assert bool(first.get("message_id_domain_mismatch")) is True
    assert bool(second.get("message_id_reuse")) is True
    assert float(second.get("risk_score") or 0.0) >= float(first.get("risk_score") or 0.0)


def test_email_security_wires_header_forensics_into_evidence_and_route(monkeypatch):
    thresholds = {
        "SECURITY_THRESHOLDS": {
            "BEC_WARN_INDICATORS": 2,
            "BEC_ERROR_INDICATORS": 3,
            "IOC_WARN_COUNT": 1,
            "IOC_ERROR_COUNT": 2,
            "HEADER_FORENSICS_WARN_THRESHOLD": 0.2,
            "HEADER_FORENSICS_ERROR_THRESHOLD": 0.5,
        },
        "TICKET_RATE_LIMIT": {"enabled": False, "per_min": 100},
    }
    import src.app.security.email_security as es
    import src.app.security.email_security_rules as rules
    import src.app.security.email_security_verdict as verdict

    monkeypatch.setattr(es, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(rules, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(verdict, "load_feature_flags", lambda *_args, **_kwargs: thresholds)

    out = es.evaluate_email_security(
        {
            "message_id": "<hdr-1@evil-payments.example>",
            "from_addr": "finance@supplier.com",
            "reply_to": "finance@supplier.com",
            "subject": "Invoice update",
            "body": "Normal body",
            "received_headers": [
                "from relay1.example [203.0.113.101] by mx.example; Thu, 06 Mar 2026 10:00:00 +0000",
                "from relay2.example [203.0.113.102] by mx2.example; Thu, 06 Mar 2026 11:00:00 +0000",
            ],
            "x_originating_ip": "203.0.113.101",
            "x_mailer": "Python-Requests/2.31",
            "attachments": [],
            "dmarc_fail": False,
        },
        tenant_id="tenant-hdr",
    )
    evidence = out.get("evidence_snapshot") or {}
    hdr = evidence.get("header_forensics") or {}
    reasons = out.get("reasons") or []

    assert isinstance(hdr, dict) and float(hdr.get("risk_score") or 0.0) > 0.0
    assert "header_forensics_high_risk" in reasons or "header_forensics_review" in reasons
    assert out.get("route") in ("human_review", "security_review")
