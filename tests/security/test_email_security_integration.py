import os

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from src.app.security.email_security import evaluate_email_security


def test_bec_like_email_verdict_warn_or_error():
    email = {
        "message_id": "<abc@xyz>",
        "from_addr": "CEO <ceo@microsoft.com>",
        "reply_to": "finance@micros0ft.com",
        "subject": "Urgent wire transfer",
        "body": "Please pay invoice at https://micros0ft-payments.com immediately.",
        "attachments": [{"name": "invoice.html"}],
        "dmarc_fail": False,
    }
    v = evaluate_email_security(email, tenant_id="t1")
    assert v["severity"] in ("warning", "error"), f"Unexpected severity: {v['severity']}"
    assert v["evidence_snapshot"]["indicator_count"] >= 2
    assert "reply_to_mismatch" in (v.get("tags") or [])
    assert (v.get("playbook") or {}).get("id") in ("PB-EMAIL-002", "PB-EMAIL-001", "PB-EMAIL-003", "PB-EMAIL-004")
