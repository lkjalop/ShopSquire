"""PCI #5 — RFC 6238 TOTP primitives (dependency-free).

Verifies round-trip, the ±1-step skew window, rejection of stale/malformed codes, and that the
provisioning URI is a well-formed otpauth:// string. Uses a fixed timestamp for determinism (the
runtime forbids argless time in some contexts, but this is a plain unit test).
"""
from __future__ import annotations

from src.app.security import totp

# RFC 6238 reference: a known SHA1 secret + fixed time → a stable code.
_T = 1_700_000_000  # fixed instant for determinism


def test_now_code_verifies():
    secret = totp.generate_secret()
    code = totp.now_code(secret, at=_T)
    assert code.isdigit() and len(code) == 6
    assert totp.verify(secret, code, at=_T) is True


def test_skew_window_accepts_adjacent_step_rejects_far():
    secret = totp.generate_secret()
    code_prev = totp.now_code(secret, at=_T - 30)   # one step earlier
    code_next = totp.now_code(secret, at=_T + 30)    # one step later
    assert totp.verify(secret, code_prev, at=_T, valid_window=1) is True
    assert totp.verify(secret, code_next, at=_T, valid_window=1) is True
    # Two steps away is outside the default window.
    code_far = totp.now_code(secret, at=_T + 120)
    assert totp.verify(secret, code_far, at=_T, valid_window=1) is False


def test_wrong_code_and_malformed_rejected():
    secret = totp.generate_secret()
    good = totp.now_code(secret, at=_T)
    bad = "000000" if good != "000000" else "111111"
    assert totp.verify(secret, bad, at=_T) is False
    assert totp.verify(secret, "", at=_T) is False
    assert totp.verify(secret, "12345", at=_T) is False    # wrong length
    assert totp.verify(secret, "abcdef", at=_T) is False    # non-digit
    assert totp.verify("", good, at=_T) is False            # no secret


def test_distinct_secrets_do_not_cross_verify():
    s1, s2 = totp.generate_secret(), totp.generate_secret()
    assert totp.verify(s2, totp.now_code(s1, at=_T), at=_T) is False


def test_provisioning_uri_is_well_formed():
    secret = totp.generate_secret()
    uri = totp.provisioning_uri(secret, "owner@shopsquire.test", issuer="ShopSquire")
    assert uri.startswith("otpauth://totp/")
    assert "secret=" + secret in uri
    assert "issuer=ShopSquire" in uri
    assert "period=30" in uri and "digits=6" in uri
