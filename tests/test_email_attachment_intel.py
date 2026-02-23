import pytest

from src.app.security.email_attachment_intel import analyze_email_artifacts


def make_homoglyph_vendor_text():
    # 'IngramF' + Cyrillic small a (U+0430) + 'ke Pty Ltd' to simulate homoglyph
    return "IngramF\u0430ke Pty Ltd\nABN: [YOUR ABN]\nAccount No: 1049 3827"


def test_homoglyph_and_abn_placeholder_and_account_mismatch():
    email = {
        "subject": "Invoice",
        "body": "Please see attached",
        "vendor_domain": "ingramfake.com.au",
        "from_addr": "accounts@ingramfake.com.au",
        "attachments": [
            {
                "name": "Ingram Invoice.pdf",
                "extracted_text": make_homoglyph_vendor_text(),
                # extracted account name intentionally mismatches vendor
                "extracted_account_name": "Ingram Logistics Holdings",
                "extracted_bank_fingerprint": "",
            }
        ],
    }

    out = analyze_email_artifacts(email)
    types = set(x.get("type") for x in out.get("indicators", []))
    assert "vendor_homoglyph_impersonation" in types
    assert "abn_placeholder_detected" in types or "abn_placeholder" in out.get("parsed_fields", {})
    assert "account_name_mismatch" in types
