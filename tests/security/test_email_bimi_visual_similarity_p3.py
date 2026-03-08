from __future__ import annotations


def test_email_security_bimi_visual_similarity_adds_signal(monkeypatch):
    from src.app.security import email_security as es

    monkeypatch.setattr(
        es,
        "verify_bimi_provider_backed",
        lambda email: {
            "from_domain": "micros0ft.com",
            "provider_bimi_present": True,
            "provider_bimi_result": "pass",
            "dns": {"ok": True, "record": "v=BIMI1; l=https://micros0ft.com/logo.svg"},
            "dns_has_bimi_record": True,
            "location_check": {"ok": True, "svg_like": True},
            "verified": True,
            "failed": False,
            "visual_similarity": {
                "enabled": True,
                "from_domain": "micros0ft.com",
                "expected_domain": "microsoft.com",
                "brand_spoof_score": 0.9,
                "spoof_suspected": True,
                "logo_host_mismatch": False,
            },
        },
    )

    out = es.evaluate_email_security(
        {
            "message_id": "<bimi-visual@x>",
            "from_addr": "billing@micros0ft.com",
            "reply_to": "billing@micros0ft.com",
            "subject": "Invoice status",
            "body": "Please review invoice status update.",
            "vendor_domain": "microsoft.com",
            "dmarc_fail": False,
        },
        tenant_id="tenant-bimi-visual",
    )
    types = {str((i or {}).get("type") or "") for i in (out.get("indicators") or [])}
    assert "bimi_visual_brand_mismatch" in types
    ev = out.get("evidence_snapshot") or {}
    assert isinstance(ev.get("bimi_visual_similarity"), dict)
    assert float((ev.get("bimi_visual_similarity") or {}).get("brand_spoof_score") or 0.0) >= 0.75
    assert "bimi_visual_brand_similarity_spoof" in (out.get("reasons") or [])
