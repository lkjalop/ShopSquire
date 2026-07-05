"""Tier-1 email detectors: zero-width/bidi obfuscation, TOAD/callback phishing, and .eml thread
reconstruction. Each closes a previously-uncovered inbound vector."""
from __future__ import annotations

from src.app.security.email_security import evaluate_email_security
from src.app.services.intake_gate import normalize_email_intake, scan_obfuscation


def _types(result):
    inds = result.get("indicators") or (result.get("extracted") or {}).get("indicators") or []
    return {str((i or {}).get("type") or "") for i in inds}


# ── zero-width / bidi ────────────────────────────────────────────────────────
def test_intake_strips_and_flags_zero_width_and_bidi():
    out, meta = normalize_email_intake({
        "from_addr": "billing@pa\u202Epal.com",   # RLO override
        "subject": "Ur​gent invoice",          # zero-width space
        "body": "pay now",
    })
    assert meta["obfuscation_bidi_override"] is True
    assert meta["obfuscation_zero_width"] is True
    assert "\u202E" not in out["from_addr"] and "​" not in out["subject"]  # stripped
    assert out["from_addr"] == "billing@papal.com"


def test_bidi_override_is_hard_security_review():
    r = evaluate_email_security({"from_addr": "billing@pa\u202Epal.com", "subject": "Invoice",
                                 "body": "please pay", "attachments": []})
    assert "obfuscation_bidi_override" in _types(r)
    assert r.get("route") == "security_review"


def test_scan_obfuscation_pure():
    assert scan_obfuscation("clean text") == {"zero_width": False, "bidi_override": False}
    assert scan_obfuscation("a​b")["zero_width"] is True


# ── TOAD / callback phishing ─────────────────────────────────────────────────
def test_toad_linkless_callback_lure_routes_to_review():
    r = evaluate_email_security({
        "from_addr": "billing@vendor-support.com",
        "subject": "Urgent: your subscription auto-renews today",
        "body": "To cancel your subscription immediately, call our billing team at 1-800-555-0142. "
                "Do not reply to this email.",
        "attachments": [],
    })
    assert "callback_phishing_toad" in _types(r)
    assert r.get("route") == "human_review" and r.get("severity") == "warning"


def test_toad_does_not_fire_on_legit_phone_footer():
    r = evaluate_email_security({
        "from_addr": "team@acme.com", "subject": "Your receipt",
        "body": "Thanks for your order. Questions? Our office line is 1-800-555-0100.",
        "attachments": [],
    })
    assert "callback_phishing_toad" not in _types(r)


def test_toad_suppressed_when_a_link_is_present():
    # a callback lure that ALSO carries a link is handled by the URL/phishing-page path, not TOAD
    r = evaluate_email_security({
        "from_addr": "billing@vendor-support.com", "subject": "Renewal",
        "body": "To cancel call our billing line at 1-800-555-0142 or visit http://vendor-support.com/cancel",
        "attachments": [],
    })
    assert "callback_phishing_toad" not in _types(r)


# ── .eml thread reconstruction ───────────────────────────────────────────────
def test_eml_parse_derives_reply_chain_from_headers():
    from src.app.routers.email_security import _parse_eml_to_email_dict
    raw = (
        b"From: vendor@supplier.com\r\n"
        b"Subject: Re: Invoice 4471\r\n"
        b"Message-ID: <msg3@supplier.com>\r\n"
        b"In-Reply-To: <msg2@supplier.com>\r\n"
        b"References: <msg1@buyer.com> <msg2@supplier.com>\r\n"
        b"\r\n"
        b"Please update the remittance account.\r\n"
    )
    d = _parse_eml_to_email_dict(raw)
    assert d["reply_chain_id"] == "<msg1@buyer.com>"   # thread ROOT (first References id)
    assert d["in_reply_to"] == "<msg2@supplier.com>"


def test_eml_no_thread_headers_is_none():
    from src.app.routers.email_security import _parse_eml_to_email_dict
    d = _parse_eml_to_email_dict(b"From: a@b.com\r\nSubject: Hi\r\n\r\nbody\r\n")
    assert d["reply_chain_id"] is None and d["in_reply_to"] is None


# ── Cyrillic-alphabet homoglyph lookalike (per request) ──────────────────────
def test_cyrillic_homoglyph_domain_is_hard_security_review():
    # 'pаypal.com' — the 'а' is Cyrillic U+0430, rendering identically to Latin 'a'. Must be
    # caught as a confusable homoglyph and routed to security_review (a spoof of paypal.com).
    r = evaluate_email_security({
        "from_addr": "billing@pаypal.com", "subject": "Invoice",
        "body": "please update remittance", "attachments": [],
    })
    t = _types(r)
    assert "confusable_homoglyph_domain" in t or "lookalike_domain" in t
    assert r.get("route") == "security_review"


def test_full_cyrillic_mimic_domain_flagged():
    # 'раураl.com' — multiple Cyrillic look-alikes; the RAW non-ASCII skeleton check must fire even
    # if NFKC folding masks it.
    r = evaluate_email_security({
        "from_addr": "security@раураl.com", "subject": "Verify account",
        "body": "verify your account", "attachments": [],
    })
    assert "confusable_homoglyph_domain" in _types(r)
    assert r.get("route") == "security_review"


def test_ascii_lookalike_typosquat_still_flagged():
    # non-homoglyph control: pure ASCII typosquat 'paypa1.com' (digit one) is a lookalike, not a
    # confusable — confirms the two detectors are distinct and both live.
    r = evaluate_email_security({
        "from_addr": "billing@paypa1.com", "subject": "Invoice", "body": "pay", "attachments": [],
    })
    assert "lookalike_domain" in _types(r)
