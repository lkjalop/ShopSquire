"""Encrypted, append-only custody for raw inbound supplier-email evidence."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text


def _decode_key(raw: str) -> bytes:
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        try:
            key = base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception as exc:
            raise RuntimeError("invalid_email_evidence_encryption_key") from exc
    if len(key) != 32:
        raise RuntimeError("email_evidence_encryption_key_must_be_32_bytes")
    return key


def _keyring() -> tuple[str, Dict[str, bytes]]:
    active = str(os.getenv("EMAIL_EVIDENCE_ACTIVE_KEY_ID") or "v1").strip() or "v1"
    keys: Dict[str, bytes] = {}
    raw_ring = str(os.getenv("EMAIL_EVIDENCE_KEYS") or "").strip()
    for entry in raw_ring.split(","):
        if ":" not in entry:
            continue
        key_id, encoded = entry.split(":", 1)
        if key_id.strip() and encoded.strip():
            keys[key_id.strip()] = _decode_key(encoded.strip())
    legacy = str(os.getenv("EMAIL_EVIDENCE_ENCRYPTION_KEY") or "").strip()
    if legacy:
        keys.setdefault(active, _decode_key(legacy))
    if not keys:
        raise RuntimeError("email_evidence_encryption_key_required")
    if active not in keys:
        raise RuntimeError("email_evidence_active_key_required")
    return active, keys


def _audit(
    db,
    *,
    tenant_id: str,
    action: str,
    actor_id: str,
    purpose: str,
    evidence_id: Optional[str] = None,
    inbox_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if not str(actor_id or "").strip() or not str(purpose or "").strip():
        raise ValueError("evidence_audit_actor_and_purpose_required")
    db.execute(
        text(
            "INSERT INTO email_evidence_operation_audit "
            "(id, tenant_id, evidence_id, inbox_id, action, actor_id, purpose, "
            "metadata_json, created_at) "
            "VALUES (:id,:tenant,:evidence,:inbox,:action,:actor,:purpose,:metadata,:created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant": tenant_id,
            "evidence": evidence_id,
            "inbox": inbox_id,
            "action": action,
            "actor": actor_id,
            "purpose": purpose,
            "metadata": json.dumps(metadata or {}, sort_keys=True, default=str),
            "created_at": datetime.now(timezone.utc),
        },
    )


def _canonical(email: Dict[str, Any]) -> bytes:
    return json.dumps(
        dict(email or {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _aad(*, tenant_id: str, provider: str, provider_message_id: str) -> bytes:
    return f"{tenant_id}\0{provider}\0{provider_message_id}".encode("utf-8")


def store_raw_evidence(
    db,
    *,
    tenant_id: str,
    provider: str,
    provider_message_id: str,
    email: Dict[str, Any],
) -> str:
    """Encrypt and insert raw evidence once; never updates or overwrites an object."""
    raw = _canonical(email)
    digest = hashlib.sha256(raw).hexdigest()
    evidence_id = str(uuid.uuid4())
    nonce = os.urandom(12)
    active_key_id, keys = _keyring()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    ciphertext = AESGCM(keys[active_key_id]).encrypt(
        nonce,
        raw,
        _aad(
            tenant_id=tenant_id,
            provider=provider,
            provider_message_id=provider_message_id,
        ),
    )
    now = datetime.now(timezone.utc)
    retention_days = max(1, int(os.getenv("EMAIL_EVIDENCE_RETENTION_DAYS", "365")))
    db.execute(
        text(
            "INSERT INTO inbound_email_raw_evidence "
            "(id, tenant_id, provider, provider_message_id, sha256, cipher, encryption_key_id, nonce_b64, "
            "ciphertext_b64, retention_until, legal_hold, created_at) "
            "VALUES (:id,:tenant,:provider,:message,:sha,'AES-256-GCM',:key_id,:nonce,:ciphertext,"
            ":retention_until,:legal_hold,:created_at)"
        ),
        {
            "id": evidence_id,
            "tenant": tenant_id,
            "provider": provider,
            "message": provider_message_id,
            "sha": digest,
            "key_id": active_key_id[:64],
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "retention_until": now + timedelta(days=retention_days),
            "legal_hold": False,
            "created_at": now,
        },
    )
    return f"evidence:{evidence_id}:sha256:{digest}"


def purge_expired_evidence(
    db,
    *,
    actor_id: str,
    purpose: str,
    now: datetime | None = None,
) -> int:
    """Delete expired evidence unless an operator or legal process placed it on hold."""
    cutoff = now or datetime.now(timezone.utc)
    rows = db.execute(
        text(
            "SELECT id, tenant_id FROM inbound_email_raw_evidence "
            "WHERE legal_hold=:legal_hold AND retention_until < :now"
        ),
        {"now": cutoff, "legal_hold": False},
    ).fetchall()
    for row in rows:
        _audit(
            db,
            tenant_id=str(row[1]),
            evidence_id=str(row[0]),
            action="retention_deleted",
            actor_id=actor_id,
            purpose=purpose,
            metadata={"retention_cutoff": cutoff.isoformat()},
        )
    result = db.execute(
        text(
            "DELETE FROM inbound_email_raw_evidence "
            "WHERE legal_hold=:legal_hold AND retention_until < :now"
        ),
        {"now": cutoff, "legal_hold": False},
    )
    return int(result.rowcount or 0)


def load_raw_evidence(
    db,
    *,
    tenant_id: str,
    evidence_ref: str,
    actor_id: str,
    purpose: str,
    inbox_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Authorized internal read used by the enrichment worker; AEAD rejects tampering."""
    parts = str(evidence_ref or "").split(":")
    if len(parts) < 2 or parts[0] != "evidence":
        raise ValueError("invalid_email_evidence_reference")
    row = db.execute(
        text(
            "SELECT provider, provider_message_id, nonce_b64, ciphertext_b64, encryption_key_id "
            "FROM inbound_email_raw_evidence WHERE id=:id AND tenant_id=:tenant"
        ),
        {"id": parts[1], "tenant": tenant_id},
    ).fetchone()
    if not row:
        raise ValueError("email_evidence_not_found")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _, keys = _keyring()
    key_id = str(row[4])
    if key_id not in keys:
        raise RuntimeError("email_evidence_decryption_key_unavailable")
    raw = AESGCM(keys[key_id]).decrypt(
        base64.b64decode(row[2]),
        base64.b64decode(row[3]),
        _aad(
            tenant_id=tenant_id,
            provider=str(row[0]),
            provider_message_id=str(row[1]),
        ),
    )
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("invalid_email_evidence_payload")
    _audit(
        db,
        tenant_id=tenant_id,
        evidence_id=parts[1],
        inbox_id=inbox_id,
        action="read",
        actor_id=actor_id,
        purpose=purpose,
        metadata={"key_id": key_id},
    )
    return decoded


def set_legal_hold(
    db,
    *,
    tenant_id: str,
    evidence_ref: str,
    enabled: bool,
    actor_id: str,
    purpose: str,
) -> None:
    parts = str(evidence_ref or "").split(":")
    if len(parts) < 2 or parts[0] != "evidence":
        raise ValueError("invalid_email_evidence_reference")
    result = db.execute(
        text(
            "UPDATE inbound_email_raw_evidence SET legal_hold=:enabled "
            "WHERE id=:id AND tenant_id=:tenant"
        ),
        {"enabled": bool(enabled), "id": parts[1], "tenant": tenant_id},
    )
    if not result.rowcount:
        raise ValueError("email_evidence_not_found")
    _audit(
        db,
        tenant_id=tenant_id,
        evidence_id=parts[1],
        action="legal_hold_enabled" if enabled else "legal_hold_disabled",
        actor_id=actor_id,
        purpose=purpose,
    )


def rotate_evidence_keys(
    db,
    *,
    tenant_id: str,
    actor_id: str,
    purpose: str,
    limit: int = 100,
) -> int:
    active_key_id, keys = _keyring()
    rows = db.execute(
        text(
            "SELECT id, provider, provider_message_id, nonce_b64, ciphertext_b64, encryption_key_id "
            "FROM inbound_email_raw_evidence WHERE tenant_id=:tenant "
            "AND encryption_key_id<>:active ORDER BY created_at LIMIT :limit"
        ),
        {"tenant": tenant_id, "active": active_key_id, "limit": max(1, min(limit, 1000))},
    ).fetchall()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    rotated = 0
    for row in rows:
        old_key_id = str(row[5])
        if old_key_id not in keys:
            raise RuntimeError(f"email_evidence_decryption_key_unavailable:{old_key_id}")
        aad = _aad(
            tenant_id=tenant_id,
            provider=str(row[1]),
            provider_message_id=str(row[2]),
        )
        plaintext = AESGCM(keys[old_key_id]).decrypt(
            base64.b64decode(row[3]),
            base64.b64decode(row[4]),
            aad,
        )
        nonce = os.urandom(12)
        ciphertext = AESGCM(keys[active_key_id]).encrypt(nonce, plaintext, aad)
        db.execute(
            text(
                "UPDATE inbound_email_raw_evidence SET encryption_key_id=:key_id, "
                "nonce_b64=:nonce, ciphertext_b64=:ciphertext WHERE id=:id AND tenant_id=:tenant"
            ),
            {
                "key_id": active_key_id,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "id": row[0],
                "tenant": tenant_id,
            },
        )
        _audit(
            db,
            tenant_id=tenant_id,
            evidence_id=str(row[0]),
            action="key_rotated",
            actor_id=actor_id,
            purpose=purpose,
            metadata={"from_key_id": old_key_id, "to_key_id": active_key_id},
        )
        rotated += 1
    return rotated
