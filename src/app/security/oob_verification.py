"""Out-of-band (OOB) verification service for bank-change events.

When a bank-change signal fires (e.g. from email_attachment_intel), the
system creates a verification request that must be confirmed through an
independent channel (phone, SMS, or email to a pre-registered contact)
before the payment change is processed.

This module is intentionally transport-agnostic — it tracks OOB
verification state and delegates actual delivery to pluggable backends
(Twilio, SES, etc.) via a simple callback interface.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class OOBStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    CONFIRMED = "confirmed"
    DENIED = "denied"
    EXPIRED = "expired"


class OOBChannel(str, Enum):
    SMS = "sms"
    EMAIL = "email"
    PHONE_CALL = "phone_call"


# ---------------------------------------------------------------------------
# In-memory store (swap for DB/Redis in production)
# ---------------------------------------------------------------------------
_store: Dict[str, Dict[str, Any]] = {}

# Pluggable delivery backends -------------------------------------------------
_delivery_backends: Dict[OOBChannel, Callable[..., bool]] = {}


def register_delivery_backend(channel: OOBChannel, fn: Callable[..., bool]) -> None:
    """Register a callable that sends the OOB challenge.

    ``fn(destination, token, context) -> bool`` must return True on success.
    """
    _delivery_backends[channel] = fn


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

_TOKEN_BYTES = 6  # 6 bytes → 12 hex chars
_EXPIRY_SECONDS = int(os.getenv("OOB_EXPIRY_SECONDS", "3600"))

_HMAC_KEY = os.getenv("OOB_HMAC_KEY", "shopsquire-oob-default-key").encode()


def _make_token() -> str:
    return secrets.token_hex(_TOKEN_BYTES)


def _sign(request_id: str, token: str) -> str:
    return hmac.new(_HMAC_KEY, f"{request_id}:{token}".encode(), hashlib.sha256).hexdigest()


def create_verification(
    *,
    vendor_domain: str,
    trigger_signal: str,
    invoice_ref: str = "",
    amount: str = "",
    channel: OOBChannel = OOBChannel.EMAIL,
    destination: str = "",
    context: Optional[Dict[str, Any]] = None,
    trace_id: str = "",
) -> Dict[str, Any]:
    """Create a new OOB verification request and return its metadata."""
    request_id = secrets.token_urlsafe(16)
    token = _make_token()
    now = time.time()
    record = {
        "request_id": request_id,
        "vendor_domain": vendor_domain,
        "trigger_signal": trigger_signal,
        "invoice_ref": invoice_ref,
        "amount": amount,
        "channel": channel.value,
        "destination": destination,
        "status": OOBStatus.PENDING.value,
        "token_hash": _sign(request_id, token),
        "created_at": now,
        "expires_at": now + _EXPIRY_SECONDS,
        "trace_id": trace_id,
        "context": context or {},
        "attempts": 0,
    }
    _store[request_id] = record

    # Attempt delivery via registered backend
    backend = _delivery_backends.get(channel)
    if backend:
        try:
            ok = backend(destination, token, record)
            if ok:
                record["status"] = OOBStatus.SENT.value
        except Exception:
            pass  # delivery failure logged externally

    return {
        "request_id": request_id,
        "status": record["status"],
        "channel": channel.value,
        "expires_at": record["expires_at"],
        # Token is returned ONLY on creation so the caller can relay it
        # via the chosen channel.  Never persisted in plain text.
        "token": token,
    }


def confirm_verification(request_id: str, token: str) -> Dict[str, Any]:
    """Confirm (or deny) an OOB verification by providing the token."""
    record = _store.get(request_id)
    if not record:
        return {"ok": False, "error": "not_found"}

    if record["status"] in (OOBStatus.CONFIRMED.value, OOBStatus.DENIED.value):
        return {"ok": False, "error": "already_resolved", "status": record["status"]}

    if time.time() > record["expires_at"]:
        record["status"] = OOBStatus.EXPIRED.value
        return {"ok": False, "error": "expired"}

    record["attempts"] += 1
    expected = _sign(request_id, token)
    if hmac.compare_digest(expected, record["token_hash"]):
        record["status"] = OOBStatus.CONFIRMED.value
        return {"ok": True, "status": OOBStatus.CONFIRMED.value, "request_id": request_id}
    else:
        if record["attempts"] >= 5:
            record["status"] = OOBStatus.DENIED.value
            return {"ok": False, "error": "max_attempts", "status": OOBStatus.DENIED.value}
        return {"ok": False, "error": "invalid_token", "attempts_remaining": 5 - record["attempts"]}


def deny_verification(request_id: str) -> Dict[str, Any]:
    """Explicitly deny / cancel an OOB verification."""
    record = _store.get(request_id)
    if not record:
        return {"ok": False, "error": "not_found"}
    record["status"] = OOBStatus.DENIED.value
    return {"ok": True, "status": OOBStatus.DENIED.value}


def get_verification(request_id: str) -> Optional[Dict[str, Any]]:
    """Return the current state of a verification request (without token)."""
    record = _store.get(request_id)
    if not record:
        return None
    # Expire if past TTL
    if record["status"] == OOBStatus.PENDING.value and time.time() > record["expires_at"]:
        record["status"] = OOBStatus.EXPIRED.value
    return {k: v for k, v in record.items() if k != "token_hash"}


def list_pending(vendor_domain: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all pending/sent verification requests, optionally filtered."""
    now = time.time()
    results = []
    for r in _store.values():
        if r["status"] in (OOBStatus.PENDING.value, OOBStatus.SENT.value):
            if now > r["expires_at"]:
                r["status"] = OOBStatus.EXPIRED.value
                continue
            if vendor_domain and r["vendor_domain"] != vendor_domain:
                continue
            results.append({k: v for k, v in r.items() if k != "token_hash"})
    return results


# ---------------------------------------------------------------------------
# Integration helper — call from email_attachment_intel or email_security
# ---------------------------------------------------------------------------

def requires_oob(indicators: List[Dict[str, Any]]) -> bool:
    """Return True if any indicator should trigger OOB verification."""
    OOB_TRIGGER_TYPES = {
        "bank_fingerprint_baseline_mismatch",
        "bank_fingerprint_extracted_mismatch",
        "account_name_mismatch",
        "vendor_homoglyph_impersonation",
    }
    return any(ind.get("type") in OOB_TRIGGER_TYPES for ind in indicators)
