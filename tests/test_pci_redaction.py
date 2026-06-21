"""PCI Req 3/4 — card PANs must never reach logs, decision traces, or LLM input.

scrub_pii is the choke point for both redact_for_trace (every decision-trace write) and
security_sanitize (LLM-bound payloads). These tests prove PANs/CVV are masked through ALL three,
while SKUs / model numbers / prices are NOT over-redacted.
"""
from __future__ import annotations

from src.app.deps import redact_for_trace, scrub_pii, security_sanitize
from src.app.security.pci import redact_pci

_VISA = "4111 1111 1111 1111"  # canonical test PAN (passes Luhn)
_MASK = "[REDACTED_CARD]"


# ── the masker itself ──
def test_redact_pci_masks_luhn_valid_pan():
    assert _MASK in redact_pci(f"my card is {_VISA} thanks")
    assert "4111" not in redact_pci(_VISA)


def test_redact_pci_masks_dashed_and_compact_pans():
    assert _MASK in redact_pci("4111-1111-1111-1111")
    assert _MASK in redact_pci("4111111111111111")


def test_redact_pci_masks_fake_pan_with_card_context():
    # Non-Luhn digits but explicit card context -> still masked (demo paste protection).
    assert _MASK in redact_pci("credit card number 1234 5678 9012 3456")


def test_redact_pci_masks_cvv_with_hint_only():
    assert "[REDACTED_CVV]" in redact_pci("CVV: 123")
    assert "[REDACTED_CVV]" in redact_pci("security code 4321")


def test_redact_pci_does_not_overredact_skus_or_specs():
    # No card context + non-Luhn -> left intact (avoid nuking product data).
    assert redact_pci("Dell Inspiron 14 7440 with 16GB RAM, 512GB SSD") == \
        "Dell Inspiron 14 7440 with 16GB RAM, 512GB SSD"
    assert redact_pci("price $1899, 240Hz, model GAM-0007") == "price $1899, 240Hz, model GAM-0007"
    # A bare 3-digit number without a CVV hint must NOT be masked.
    assert "[REDACTED_CVV]" not in redact_pci("it has 165 fps")


# ── wired through the choke point ──
def test_scrub_pii_masks_pan():
    out = scrub_pii(f"please refund my card {_VISA}")
    assert _MASK in out and "4111" not in out


def test_security_sanitize_masks_pan_in_nested_payload():
    payload = {"note": f"card {_VISA}", "items": [{"msg": "pay with 4111-1111-1111-1111"}]}
    out = security_sanitize(payload)
    assert _MASK in out["note"]
    assert _MASK in out["items"][0]["msg"]


def test_redact_for_trace_masks_pan():
    out = redact_for_trace({"user_text": f"my number is {_VISA}"})
    assert _MASK in out["user_text"] and "1111 1111" not in out["user_text"]


def test_scrub_pii_still_masks_other_pii_and_keeps_ids():
    out = scrub_pii("email a@b.com, order ORD-123456 stays")
    assert "[REDACTED_EMAIL]" in out
    assert "ORD-123456" in out  # system IDs preserved
