import os

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from src.app.security.email_security_rules import extract_indicators, extract_domain


def test_reply_to_mismatch_indicator():
    email = {
        "from_addr": "CEO <ceo@microsoft.com>",
        "reply_to": "finance@micros0ft.com",
        "subject": "Urgent: wire transfer",
        "body": "Please process payment ASAP.",
    }
    out = extract_indicators(email)
    types = [i["type"] for i in out["indicators"]]
    assert "reply_to_mismatch" in types


def test_lookalike_domain_detection():
    d = extract_domain("alerts@micros0ft.com")
    # micros0ft.com should be flagged as lookalike of microsoft.com
    email = {
        "from_addr": "alerts@micros0ft.com",
        "reply_to": "alerts@micros0ft.com",
        "subject": "Invoice",
        "body": "Your invoice is attached.",
    }
    out = extract_indicators(email)
    hits = [i for i in out["indicators"] if i["type"] == "lookalike_domain"]
    assert hits, f"Expected lookalike hit for domain {d}"


def test_arc_chain_invalid_indicator():
    email = {
        "from_addr": "Vendor <billing@supplier.com>",
        "reply_to": "billing@supplier.com",
        "subject": "Invoice",
        "body": "Please process",
        "arc_cv": "fail",
        "arc_chain_valid": False,
    }
    out = extract_indicators(email)
    types = [i["type"] for i in out["indicators"]]
    assert "arc_chain_invalid" in types


def test_bimi_failed_indicator():
    email = {
        "from_addr": "Vendor <billing@supplier.com>",
        "reply_to": "billing@supplier.com",
        "subject": "Invoice",
        "body": "Please process",
        "bimi_present": True,
        "bimi_result": "fail",
    }
    out = extract_indicators(email)
    types = [i["type"] for i in out["indicators"]]
    assert "bimi_validation_failed" in types
