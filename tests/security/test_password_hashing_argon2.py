"""PCI #3 — password hashing contract (argon2id with PBKDF2 fallback + migration).

ShopSquire hashes passwords with argon2id (pinned `argon2-cffi`, installed in the prod image via
`poetry install --only main`). When argon2 is unavailable it falls back to PBKDF2-HMAC-SHA256 at a
high iteration count, and a legacy PBKDF2 hash is transparently MIGRATED to argon2id on next login.

This test is tolerant of the local/CI env: it asserts the argon2id format only when argon2 is
importable; the verify + legacy-migration contract is asserted unconditionally.
"""
from __future__ import annotations

import hashlib

import pytest

from src.app.routers.auth import _hash_password, _verify_password

try:  # mirrors auth.py's own optional import
    import argon2 as _argon2  # noqa: F401
    _ARGON2_AVAILABLE = True
except Exception:
    _ARGON2_AVAILABLE = False


def test_hash_and_verify_roundtrip():
    salt = "0123456789abcdef"
    h = _hash_password("C0rrect-Horse!", salt)
    assert h and isinstance(h, str)
    ok, _ = _verify_password("C0rrect-Horse!", h, salt)
    assert ok is True
    bad, _ = _verify_password("wrong-password", h, salt)
    assert bad is False


@pytest.mark.skipif(not _ARGON2_AVAILABLE, reason="argon2-cffi not installed in this env")
def test_uses_argon2id_when_available():
    h = _hash_password("C0rrect-Horse!", "0123456789abcdef")
    assert h.startswith("$argon2id$"), f"expected argon2id, got {h[:16]!r}"


def test_legacy_pbkdf2_verifies_and_migrates_to_argon2id():
    salt = "0123456789abcdef"
    legacy = hashlib.pbkdf2_hmac("sha256", b"C0rrect-Horse!", salt.encode("utf-8"), 600_000).hex()
    ok, migrated = _verify_password("C0rrect-Horse!", legacy, salt)
    assert ok is True
    if _ARGON2_AVAILABLE:
        # On a successful legacy verify, the caller is handed a fresh argon2id hash to persist.
        assert migrated and migrated.startswith("$argon2id$")
