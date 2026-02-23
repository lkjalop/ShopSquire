import base64


def test_ingest_gate_blocks_executable_attachment():
    from src.app.security.email_security import evaluate_email_security

    payload = {
        "message_id": "ingest-1",
        "from_addr": "alerts@supplier.example",
        "reply_to": "alerts@supplier.example",
        "subject": "Please review attachment",
        "body": "See attached file.",
        "attachments": [
            {
                "name": "runme.exe",
                "content_type": "application/octet-stream",
                "content_b64": base64.b64encode(b"MZ" + b"\x00" * 128).decode("ascii"),
            }
        ],
    }
    out = evaluate_email_security(payload, tenant_id="tenant-ingest")
    assert out.get("route") == "security_review"
    assert "ingest_gate_blocked_attachment" in (out.get("reasons") or [])
    gate = (out.get("evidence_snapshot") or {}).get("attachment_ingest_gate") or {}
    assert bool(gate.get("blocked")) is True


def test_ocr_qr_allowlist_blocks_external_url():
    from src.app.security.email_security import evaluate_email_security

    payload = {
        "message_id": "ingest-qr-1",
        "from_addr": "catalog@supplier.example",
        "reply_to": "catalog@supplier.example",
        "subject": "Updated catalog",
        "body": "Attached image includes a QR for payments",
        "attachments": [
            {
                "name": "catalog-note.png",
                "content_type": "image/png",
                "extracted_text": "Scan and pay now at https://evil.example/pay?id=42",
            }
        ],
    }
    out = evaluate_email_security(payload, tenant_id="tenant-ingest")
    reasons = out.get("reasons") or []
    assert "qr_url_not_allowlisted" in reasons
    ocr_gate = (out.get("evidence_snapshot") or {}).get("ocr_qr_sanitization") or {}
    assert int(ocr_gate.get("blocked_qr_url_count") or 0) >= 1


def test_trust_case_forced_reauth_on_malicious_detonation(monkeypatch):
    import src.app.security.email_security as es

    monkeypatch.setattr(
        es,
        "detonate_targets",
        lambda _urls, _hashes: {"provider": "sandbox-mock", "malicious": True, "score": 0.99, "findings": [{"signal": "c2"}]},
    )

    payload = {
        "message_id": "trust-1",
        "from_addr": "finance@supplier.example",
        "reply_to": "finance@supplier.example",
        "subject": "Invoice follow up",
        "body": "please verify invoice now",
        "attachments": [],
    }
    out = es.evaluate_email_security(payload, tenant_id="tenant-trust")
    trust_case = out.get("trust_case") or {}
    assert bool(trust_case.get("forced_reauth")) is True
    assert "force_reauth" in (trust_case.get("actions") or [])
    assert out.get("route") == "security_review"
