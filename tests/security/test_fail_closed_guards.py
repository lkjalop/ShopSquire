"""P0-2 fail-closed regression tests — each pins a guard that previously defaulted to ALLOW on an
internal exception (a scanner crash, a malformed config) to now fail CLOSED. A regression here would
silently re-open the hole (credential egress, cross-tenant access, unverified spend)."""
import os


def test_outbound_integrity_scan_failure_blocks(monkeypatch):
    # dlp secret scanner raising must force BLOCK, never resolve to allow (credential egress guard).
    import src.app.security.dlp_export as dlp
    monkeypatch.setattr(dlp, "dlp_scrub_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    from src.app.services.fulfillment.outbound_integrity import scan_outbound_supplier_message
    v = scan_outbound_supplier_message("RFQ", "please quote 10 units")
    assert v["action"] == "block"
    assert v["dlp"]["scan_failed"] is True
    assert "secret_scan_failed_fail_closed" in v["findings"]


def test_outbound_email_monitor_scan_failure_reviews(monkeypatch):
    import src.app.security.dlp_export as dlp
    monkeypatch.setattr(dlp, "dlp_scrub_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    from src.app.services.outbound_email_monitor import scan_outbound_content_dlp
    v = scan_outbound_content_dlp("subject", "body")
    assert v["action"] == "review" and v.get("scan_failed") is True     # not 'allow'


def test_abac_malformed_allowlist_denies(monkeypatch):
    from src.app.security.auth import _abac_tenant_allow
    # a CONFIGURED but malformed allowlist → deny (was: allow-all, silently disabling the restriction)
    monkeypatch.setenv("ABAC_TENANT_ALLOWLIST_JSON", "{not valid json")
    assert _abac_tenant_allow("merchant", "t1") is False
    # unset allowlist → allow (intentional: no restriction configured)
    monkeypatch.delenv("ABAC_TENANT_ALLOWLIST_JSON", raising=False)
    assert _abac_tenant_allow("merchant", "t1") is True
    # well-formed allowlist still enforced
    monkeypatch.setenv("ABAC_TENANT_ALLOWLIST_JSON", '{"merchant": ["t1"]}')
    assert _abac_tenant_allow("merchant", "t1") is True
    assert _abac_tenant_allow("merchant", "t2") is False


def test_email_attachment_ingest_gate_failure_blocks(monkeypatch):
    import src.app.security.email_security as es

    monkeypatch.setattr(
        es,
        "strict_attachment_ingest_gate",
        lambda _email: (_ for _ in ()).throw(RuntimeError("scanner unavailable")),
    )
    out = es.evaluate_email_security(
        {
            "message_id": "fail-closed-ingest",
            "from_addr": "quotes@supplier.example",
            "subject": "Quote",
            "body": "Attached quote.",
            "attachments": [{"name": "quote.pdf", "content_type": "application/pdf"}],
        },
        tenant_id="tenant-fail-closed",
    )
    gate = (out.get("evidence_snapshot") or {}).get("attachment_ingest_gate") or {}
    assert gate.get("blocked") is True
    assert "ingest_gate_unavailable" in (out.get("reasons") or [])
    assert out.get("route") == "security_review"


def test_email_ocr_sanitizer_failure_blocks_attachment(monkeypatch):
    import src.app.security.email_security as es

    monkeypatch.setattr(
        es,
        "sanitize_attachment_ocr_for_llm",
        lambda _email: (_ for _ in ()).throw(RuntimeError("sanitizer unavailable")),
    )
    out = es.evaluate_email_security(
        {
            "message_id": "fail-closed-ocr",
            "from_addr": "quotes@supplier.example",
            "subject": "Quote",
            "body": "Attached quote.",
            "attachments": [{"name": "quote.pdf", "content_type": "application/pdf"}],
        },
        tenant_id="tenant-fail-closed",
    )
    gate = (out.get("evidence_snapshot") or {}).get("ocr_qr_sanitization") or {}
    assert gate.get("blocked") is True
    assert "ocr_sanitization_unavailable" in (out.get("reasons") or [])
    assert out.get("route") == "security_review"
