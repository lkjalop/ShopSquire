from src.app.security.guardrails import sanitize_serials, extract_typed_entities, apply_guardrails
from src.app.security.utils import is_card_like, luhn_check, normalize_digits


def test_normalize_and_luhn():
    s = "4111 1111 1111 1111"
    assert normalize_digits(s) == "4111111111111111"
    assert luhn_check(normalize_digits(s)) is True


def test_is_card_like_detects_card():
    s = "My card is 4111-1111-1111-1111 exp 12/25"
    is_card, details = is_card_like(s)
    assert is_card is True
    assert details.get("luhn") is True


def test_sanitize_serials_hash_and_redact():
    txt = "Device S/N: ABCD-1234 and serial number: 9999-8888"
    hashed, actions = sanitize_serials(txt, mode="hash")
    assert any(a.get("action") == "hash" for a in actions)
    redacted, actions2 = sanitize_serials(txt, mode="redact")
    assert any(a.get("action") == "redact" for a in actions2)


def test_apply_guardrails_returns_structure():
    msg = {"text": "Here is my serial S/N: ABC12345 and card 4111 1111 1111 1111"}
    meta = {"conversation_state": "checkout"}
    out = apply_guardrails(msg, meta)
    assert isinstance(out, dict)
    assert "sanitized_payload" in out
    assert "guardrail_actions" in out
