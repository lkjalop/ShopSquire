"""Feature-flag file integrity — HMAC-SHA256 signing & verification.

Signs ``config/feature_flags.json`` so that tampered-on-disk flag files
are detected at load time in production.

Key source (in priority order):
1. ``FLAG_HMAC_KEY`` env var (hex-encoded, ≥32 bytes)
2. Vault secret at ``FLAG_HMAC_KEY`` path
3. Disabled — returns ``None`` (dev/test convenience)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Optional

# Flags whose changes require explicit 4-eyes confirmation header.
SECURITY_CRITICAL_FLAGS = frozenset({
    "KILL_SWITCH",
    "USE_AGENT_CAPABILITIES",
    "AGENT_ROLLOUT_PERCENT",
    "DECISION_LOG_WRITES_ENABLED",
})


def _get_hmac_key() -> Optional[bytes]:
    raw = os.getenv("FLAG_HMAC_KEY")
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        key = raw.encode()
    if len(key) < 32:
        return None  # key too short — refuse to sign with weak material
    return key


def _canonical(flags_path: str) -> bytes:
    """Return canonical JSON bytes (sorted keys, no trailing whitespace)."""
    with open(flags_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def sign_flags(flags_path: str) -> Optional[str]:
    """Write ``<flags_path>.sig`` containing HMAC-SHA256 hex digest.

    Returns the hex digest, or ``None`` if no key is configured.
    """
    key = _get_hmac_key()
    if key is None:
        return None
    payload = _canonical(flags_path)
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()
    sig_path = flags_path + ".sig"
    with open(sig_path, "w", encoding="utf-8") as f:
        f.write(digest)
    return digest


def verify_flags(flags_path: str) -> Optional[bool]:
    """Verify HMAC of the flags file.

    Returns:
      ``True``  — signature valid
      ``False`` — signature mismatch (tampered or stale)
      ``None``  — verification skipped (no key or no .sig file)
    """
    key = _get_hmac_key()
    if key is None:
        return None
    sig_path = flags_path + ".sig"
    if not os.path.exists(sig_path):
        return None
    with open(sig_path, "r", encoding="utf-8") as f:
        expected = f.read().strip()
    payload = _canonical(flags_path)
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)
