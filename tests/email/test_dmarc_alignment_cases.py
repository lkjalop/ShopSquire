import os
import pytest

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")


def _payload(spf: str, dkim: str, dmarc: str, policy: str):
    return {
        "message_id": "<align-case@shopsquire>",
        "from_addr": "alerts@supplier.com",
        "reply_to": "alerts@supplier.com",
        "subject": "Alignment check",
        "body": "Alignment scenario",
        "attachments": [],
        "spf_result": spf,
        "dkim_result": dkim,
        "dmarc_result": dmarc,
        "dmarc_policy": policy,
        "external_sender": True,
    }


@pytest.mark.parametrize(
    "spf,dkim,dmarc,policy,expect_route",
    [
        ("pass", "fail", "fail", "reject", "security_review"),
        ("pass", "fail", "quarantine", "p=reject", "security_review"),
        ("fail", "pass", "fail", "quarantine", "security_review"),
        # Even with perfect auth, external sender + lack of trust context can still require review.
        ("pass", "pass", "pass", "none", "human_review"),
    ],
)
def test_dmarc_misalignment_forces_security_review(spf, dkim, dmarc, policy, expect_route):
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(_payload(spf, dkim, dmarc, policy), tenant_id="t-align")
    assert out.get("route") == expect_route
    ev = out.get("evidence_snapshot") or {}
    assert (ev.get("auth_verdicts") or {}).get("dmarc_result") == dmarc
    assert (ev.get("auth_verdicts") or {}).get("dmarc_policy") == policy


def test_auth_pass_trusted_sender_auto_resolve(monkeypatch):
    # Add supplier.com to trusted sender allowlist via feature flags override
    flags = {
        "SECURITY_THRESHOLDS": {
            "TRUSTED_SENDER_DOMAINS": ["supplier.com"],
        }
    }
    import src.app.security.email_security as es
    import src.app.security.email_security_verdict as verdict
    import src.app.security.email_security_rules as rules
    monkeypatch.setattr(es, "load_feature_flags", lambda *_a, **_k: flags)
    monkeypatch.setattr(verdict, "load_feature_flags", lambda *_a, **_k: flags)
    monkeypatch.setattr(rules, "load_feature_flags", lambda *_a, **_k: flags)

    from src.app.security.email_security import evaluate_email_security
    out = evaluate_email_security(
        {
            "message_id": "<align-pass@shopsquire>",
            "from_addr": "alerts@supplier.com",
            "reply_to": "alerts@supplier.com",
            "subject": "Quarterly update",
            "body": "Normal note",
            "attachments": [],
            "spf_result": "pass",
            "dkim_result": "pass",
            "dmarc_result": "pass",
            "dmarc_policy": "none",
            "external_sender": True,
        },
        tenant_id="t-align",
    )
    assert out.get("route") == "auto_resolve"


def test_internal_sender_auth_pass_auto_resolve():
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(
        {
            "message_id": "<align-internal@shopsquire>",
            "from_addr": "ops@shopsquire.local",
            "reply_to": "ops@shopsquire.local",
            "subject": "System notice",
            "body": "Routine maintenance",
            "attachments": [],
            "spf_result": "pass",
            "dkim_result": "pass",
            "dmarc_result": "pass",
            "dmarc_policy": "none",
            "external_sender": False,
        },
        tenant_id="t-align",
    )
    assert out.get("route") in ("auto_resolve", "human_review")
    # Prefer auto_resolve when internal + auth-pass and no critical signals
    assert out.get("route") == "auto_resolve"


def test_critical_signal_overrides_to_security_review(monkeypatch):
    # Compose an email body with a LOLBin pattern to simulate high-risk content.
    from src.app.security.email_security import evaluate_email_security

    body = "User report: found powershell -enc JABwAHIAbwBjAGUAcwBzAC4u on server"
    out = evaluate_email_security(
        {
            "message_id": "<align-critical@shopsquire>",
            "from_addr": "alerts@supplier.com",
            "reply_to": "alerts@supplier.com",
            "subject": "Urgent operations",
            "body": body,
            "attachments": [],
            "spf_result": "pass",
            "dkim_result": "pass",
            "dmarc_result": "pass",
            "dmarc_policy": "none",
            "external_sender": True,
        },
        tenant_id="t-align",
    )
    assert out.get("route") == "security_review"
    assert "lolbin" in " ".join(out.get("tags") or [])
