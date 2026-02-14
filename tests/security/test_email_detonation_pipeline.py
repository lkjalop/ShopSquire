import os
import pytest

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")


def test_email_url_detonation_malicious_escalates(monkeypatch):
    from src.app.security import email_security as es

    class DummyDetonator:
        def __call__(self, urls, attachment_hashes):
            return {"provider": "stub", "malicious": True, "score": 0.91, "findings": ["eicar-like"]}

    # Patch detonation to simulate a malicious finding
    monkeypatch.setitem(es.__dict__, "detonate_targets", DummyDetonator())

    out = es.evaluate_email_security(
        {
            "message_id": "<detonate-1@shopsquire>",
            "from_addr": "alerts@supplier.com",
            "reply_to": "alerts@supplier.com",
            "subject": "Please verify",
            "body": "Visit http://evil.example/login now",
            "attachments": [],
            "external_sender": True,
        },
        tenant_id="t-detonate",
    )
    assert out.get("route") == "security_review"
    assert out.get("severity") == "error"
    det = out.get("detonation") or {}
    assert det.get("provider") == "stub"
    assert det.get("malicious") is True


def test_email_attachment_detonation_malicious_escalates(monkeypatch):
    from src.app.security import email_security as es

    class DummyDetonator:
        def __call__(self, urls, attachment_hashes):
            return {"provider": "stub", "malicious": True, "score": 0.86, "findings": ["macro-malware"]}

    monkeypatch.setitem(es.__dict__, "detonate_targets", DummyDetonator())

    out = es.evaluate_email_security(
        {
            "message_id": "<detonate-2@shopsquire>",
            "from_addr": "alerts@supplier.com",
            "reply_to": "alerts@supplier.com",
            "subject": "Invoice",
            "body": "See attachment",
            "attachments": [{"name": "invoice.xlsm", "sha256": "deadbeef"}],
            "external_sender": True,
        },
        tenant_id="t-detonate",
    )
    assert out.get("route") == "security_review"
    assert out.get("severity") == "error"
    det = out.get("detonation") or {}
    assert det.get("provider") == "stub"
    assert det.get("malicious") is True
