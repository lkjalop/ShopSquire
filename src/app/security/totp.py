"""RFC 6238 TOTP — dependency-free (stdlib only).

Real time-based one-time passwords for admin MFA (PCI #5): a per-admin base32 secret, an
``otpauth://`` provisioning URI any authenticator app (Google Authenticator, Authy, 1Password…)
can scan, and constant-time verification with a small clock-skew window. No third-party library, so
it works identically in local, CI, and the prod image with nothing to install.

Defaults match the otpauth provisioning URI we emit: SHA1, 6 digits, 30-second step (the universal
authenticator-app defaults).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
import urllib.parse
from typing import Optional

_DIGITS = 6
_STEP = 30
_ISSUER_DEFAULT = "ShopSquire"


def generate_secret(num_bytes: int = 20) -> str:
    """A fresh base32 TOTP secret (160-bit default), unpadded (authenticator apps accept either)."""
    return base64.b32encode(os.urandom(num_bytes)).decode("ascii").rstrip("=")


def _b32decode(secret: str) -> bytes:
    s = str(secret or "").strip().replace(" ", "").upper()
    pad = (-len(s)) % 8
    return base64.b32decode(s + ("=" * pad))


def _hotp(secret: str, counter: int, *, digits: int = _DIGITS) -> str:
    key = _b32decode(secret)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    truncated = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def now_code(secret: str, *, step: int = _STEP, digits: int = _DIGITS, at: Optional[float] = None) -> str:
    """The current TOTP code for ``secret`` (used by tests / for self-verification)."""
    t = int(at if at is not None else time.time())
    return _hotp(secret, t // step, digits=digits)


def verify(secret: str, code: str, *, step: int = _STEP, digits: int = _DIGITS,
           valid_window: int = 1, at: Optional[float] = None) -> bool:
    """Constant-time TOTP verification with a ±``valid_window``-step clock-skew tolerance. Returns
    False (never raises) for any malformed input or bad secret — fail-closed."""
    try:
        s = str(secret or "")
        c = str(code or "").strip()
        if not s or not c or not c.isdigit() or len(c) != digits:
            return False
        t = int(at if at is not None else time.time())
        counter = t // step
        for w in range(-valid_window, valid_window + 1):
            if hmac.compare_digest(_hotp(s, counter + w, digits=digits), c):
                return True
        return False
    except Exception:
        return False


def provisioning_uri(secret: str, account_name: str, *, issuer: str = _ISSUER_DEFAULT) -> str:
    """An ``otpauth://totp/…`` URI for QR provisioning in any authenticator app."""
    label = urllib.parse.quote(f"{issuer}:{account_name}")
    params = urllib.parse.urlencode({
        "secret": secret, "issuer": issuer,
        "algorithm": "SHA1", "digits": _DIGITS, "period": _STEP,
    })
    return f"otpauth://totp/{label}?{params}"
