"""Cryptographically verified, scoped exceptions for allocation shadow parity.

The application verifies an externally signed record; it does not hold the signing key.  An
exception explains a measured semantic difference and never transfers execution authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import text


KeyResolver = Callable[[str, str], bytes | None]


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_exception_bytes(payload: dict[str, Any]) -> bytes:
    """Return the one stable byte representation that an external approver signs."""
    required = {
        "tenant_id", "case_id", "difference_code", "rationale", "evidence_ref",
        "signer_id", "key_id", "valid_from", "expires_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError("missing_parity_exception_fields:" + ",".join(missing))
    normalized = {
        "tenant_id": str(payload["tenant_id"]).strip(),
        "case_id": str(payload["case_id"]).strip(),
        "sku": str(payload.get("sku") or "").strip() or None,
        "difference_code": str(payload["difference_code"]).strip(),
        "rationale": str(payload["rationale"]).strip(),
        "evidence_ref": str(payload["evidence_ref"]).strip(),
        "signer_id": str(payload["signer_id"]).strip(),
        "key_id": str(payload["key_id"]).strip(),
        "valid_from": _timestamp(str(payload["valid_from"])).isoformat(),
        "expires_at": _timestamp(str(payload["expires_at"])).isoformat(),
    }
    if not normalized["tenant_id"] or not normalized["case_id"]:
        raise ValueError("parity_exception_scope_required")
    if len(normalized["rationale"]) < 12 or len(normalized["evidence_ref"]) < 3:
        raise ValueError("parity_exception_evidence_required")
    if _timestamp(normalized["expires_at"]) <= _timestamp(normalized["valid_from"]):
        raise ValueError("parity_exception_expiry_invalid")
    return json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_exception_signature(
    payload: dict[str, Any], signature_b64: str, public_key_bytes: bytes,
) -> bool:
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature, canonical_exception_bytes(payload),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def store_verified_exception(
    db, *, payload: dict[str, Any], signature_b64: str, public_key_bytes: bytes,
) -> dict[str, Any]:
    """Persist only a valid external signature; replay returns the same immutable row."""
    canonical = canonical_exception_bytes(payload)
    normalized = json.loads(canonical)
    if not verify_exception_signature(normalized, signature_b64, public_key_bytes):
        raise ValueError("invalid_parity_exception_signature")
    exception_id = hashlib.sha256(canonical + b"." + signature_b64.encode("ascii")).hexdigest()
    existing = db.execute(text(
        "SELECT revoked_at FROM allocation_parity_exception WHERE id=:id"
    ), {"id": exception_id}).fetchone()
    if existing:
        return {"id": exception_id, "status": "revoked" if existing[0] else "active", "idempotent": True}
    db.execute(text(
        "INSERT INTO allocation_parity_exception "
        "(id,tenant_id,case_id,sku,difference_code,rationale,evidence_ref,signer_id,key_id,"
        "payload_json,signature_b64,valid_from,expires_at,created_at) VALUES "
        "(:id,:tenant,:case_id,:sku,:code,:rationale,:evidence,:signer,:key_id,:payload,"
        ":signature,:valid_from,:expires_at,:created_at)"
    ), {
        "id": exception_id, "tenant": normalized["tenant_id"], "case_id": normalized["case_id"],
        "sku": normalized["sku"], "code": normalized["difference_code"],
        "rationale": normalized["rationale"], "evidence": normalized["evidence_ref"],
        "signer": normalized["signer_id"], "key_id": normalized["key_id"],
        "payload": canonical.decode("utf-8"), "signature": signature_b64,
        "valid_from": normalized["valid_from"], "expires_at": normalized["expires_at"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"id": exception_id, "status": "active", "idempotent": False}


def verified_exception_scopes(
    db, *, tenant_id: str, case_id: str, key_resolver: KeyResolver,
    allowed_codes: Iterable[str], as_of: datetime | None = None,
) -> dict[str, Any]:
    """Fail closed on expired, revoked, unknown-key, tampered, or unknown-code records."""
    now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    allowed = frozenset(str(code) for code in allowed_codes)
    rows = db.execute(text(
        "SELECT id,sku,difference_code,key_id,payload_json,signature_b64,valid_from,expires_at,"
        "revoked_at,rationale,evidence_ref,signer_id FROM allocation_parity_exception "
        "WHERE tenant_id=:tenant AND case_id=:case_id "
        "ORDER BY created_at,id"
    ), {"tenant": tenant_id, "case_id": case_id}).fetchall()
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for row in rows:
        (exception_id, sku, code, key_id, payload_json, signature, valid_from, expires_at,
         revoked, rationale, evidence_ref, signer_id) = row
        reason = None
        try:
            payload = json.loads(str(payload_json))
        except json.JSONDecodeError:
            payload = {}
        if revoked:
            reason = "revoked"
        elif str(code) not in allowed:
            reason = "unsupported_difference_code"
        else:
            key = key_resolver(tenant_id, str(key_id))
            if not key:
                reason = "verification_key_unavailable"
            elif not verify_exception_signature(payload, str(signature), key):
                reason = "signature_verification_failed"
            else:
                projected = {
                    "tenant_id": tenant_id, "case_id": case_id, "sku": sku,
                    "difference_code": code, "rationale": rationale,
                    "evidence_ref": evidence_ref, "signer_id": signer_id, "key_id": key_id,
                    "valid_from": _timestamp(str(valid_from)).isoformat(),
                    "expires_at": _timestamp(str(expires_at)).isoformat(),
                }
                if payload != projected:
                    reason = "signed_payload_mismatch"
                elif payload.get("tenant_id") != tenant_id or payload.get("case_id") != case_id:
                    reason = "signed_scope_mismatch"
                elif now < _timestamp(payload["valid_from"]) or now >= _timestamp(payload["expires_at"]):
                    reason = "outside_validity_window"
        if reason:
            rejected.append({"id": str(exception_id), "reason": reason})
        else:
            accepted.append({"id": str(exception_id), "difference_code": str(code), "sku": sku})
    return {"accepted": accepted, "rejected": rejected, "as_of": now.isoformat()}
