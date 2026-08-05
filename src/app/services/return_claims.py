"""Tenant-scoped return/repair claims and encrypted raw-artifact custody.

Raw customer files are encrypted before being written to the object-store adapter.
Only bounded, sanitized observations are stored in operational tables.  A receipt or
OCR string is evidence supplied by a claimant; it never becomes order authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from sqlalchemy import text


CLAIM_STATES = {
    "received", "evidence_pending", "needs_info", "under_review", "approved",
    "repair_authorized", "in_transit", "received_at_facility", "repair_in_progress",
    "repaired", "replacement_sent", "refund_pending", "refunded", "rejected", "closed",
}

ALLOWED_TRANSITIONS = {
    "received": {"evidence_pending", "needs_info", "under_review", "rejected"},
    "evidence_pending": {"needs_info", "under_review", "rejected"},
    "needs_info": {"evidence_pending", "under_review", "rejected", "closed"},
    "under_review": {"approved", "repair_authorized", "refund_pending", "rejected", "needs_info"},
    "approved": {"in_transit", "replacement_sent", "refund_pending", "closed"},
    "repair_authorized": {"in_transit", "received_at_facility", "closed"},
    "in_transit": {"received_at_facility", "needs_info"},
    "received_at_facility": {"repair_in_progress", "replacement_sent", "refund_pending"},
    "repair_in_progress": {"repaired", "replacement_sent", "refund_pending"},
    "repaired": {"in_transit", "closed"},
    "replacement_sent": {"closed"},
    "refund_pending": {"refunded", "rejected"},
    "refunded": {"closed"},
    "rejected": {"under_review", "closed"},
    "closed": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    name = Path(str(value or "upload.bin")).name
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:160] or "upload.bin"


def _decode_key(raw: str) -> bytes:
    try:
        value = bytes.fromhex(raw)
    except ValueError:
        try:
            value = base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception as exc:
            raise RuntimeError("invalid_return_evidence_encryption_key") from exc
    if len(value) != 32:
        raise RuntimeError("return_evidence_encryption_key_must_be_32_bytes")
    return value


def _keyring() -> tuple[str, dict[str, bytes]]:
    active = str(os.getenv("RETURN_EVIDENCE_ACTIVE_KEY_ID") or "v1").strip() or "v1"
    ring: dict[str, bytes] = {}
    provider = str(os.getenv("RETURN_EVIDENCE_KEY_PROVIDER") or "env").strip().lower()
    if provider in {"azure", "azure_key_vault"}:
        vault_url = str(os.getenv("RETURN_EVIDENCE_KEY_VAULT_URL") or "").strip()
        if not vault_url:
            raise RuntimeError("return_evidence_key_vault_url_required")
        key_ids = {
            item.strip()
            for item in str(os.getenv("RETURN_EVIDENCE_KEY_IDS") or active).split(",")
            if item.strip()
        }
        key_ids.add(active)
        from src.app.providers.azure import get_key_vault_secret

        for key_id in key_ids:
            secret_name = f"return-evidence-key-{key_id}".replace("_", "-")
            encoded = get_key_vault_secret(vault_url, secret_name)
            if encoded:
                ring[key_id] = _decode_key(str(encoded))
    elif provider not in {"env", "local"}:
        raise RuntimeError(f"unsupported_return_evidence_key_provider:{provider}")
    for entry in str(os.getenv("RETURN_EVIDENCE_KEYS") or "").split(","):
        if ":" in entry:
            key_id, encoded = entry.split(":", 1)
            if key_id.strip() and encoded.strip():
                ring[key_id.strip()] = _decode_key(encoded.strip())
    legacy = str(os.getenv("RETURN_EVIDENCE_ENCRYPTION_KEY") or "").strip()
    if legacy:
        ring.setdefault(active, _decode_key(legacy))
    if not ring or active not in ring:
        raise RuntimeError("return_evidence_encryption_key_required")
    return active, ring


_ENVELOPE_MAGIC = b"SQRE2"


def _encrypt_envelope(raw: bytes, *, aad: bytes, key_id: str, kek: bytes) -> bytes:
    """Encrypt with a random object DEK, wrapped by the versioned tenant KEK."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.keywrap import aes_key_wrap

    dek = os.urandom(32)
    nonce = os.urandom(12)
    wrapped = aes_key_wrap(kek, dek)
    header = json.dumps(
        {
            "v": 2,
            "kid": key_id,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "wrapped_dek": base64.urlsafe_b64encode(wrapped).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(header) > 4096:
        raise RuntimeError("return_evidence_envelope_header_too_large")
    return _ENVELOPE_MAGIC + len(header).to_bytes(4, "big") + header + AESGCM(dek).encrypt(nonce, raw, aad)


def _decrypt_envelope(encrypted: bytes, *, aad: bytes, key_id: str, kek: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.keywrap import aes_key_unwrap

    if not encrypted.startswith(_ENVELOPE_MAGIC):
        # Backward-compatible reader for evidence written before envelope v2.
        if len(encrypted) < 13:
            raise ValueError("invalid_return_evidence_ciphertext")
        return AESGCM(kek).decrypt(encrypted[:12], encrypted[12:], aad)
    if len(encrypted) < len(_ENVELOPE_MAGIC) + 5:
        raise ValueError("invalid_return_evidence_envelope")
    offset = len(_ENVELOPE_MAGIC)
    header_size = int.from_bytes(encrypted[offset:offset + 4], "big")
    if header_size < 10 or header_size > 4096 or len(encrypted) <= offset + 4 + header_size:
        raise ValueError("invalid_return_evidence_envelope_header")
    header = json.loads(encrypted[offset + 4:offset + 4 + header_size])
    if int(header.get("v") or 0) != 2 or str(header.get("kid") or "") != key_id:
        raise ValueError("return_evidence_envelope_key_mismatch")
    nonce = base64.urlsafe_b64decode(str(header["nonce"]).encode("ascii"))
    wrapped = base64.urlsafe_b64decode(str(header["wrapped_dek"]).encode("ascii"))
    dek = aes_key_unwrap(kek, wrapped)
    return AESGCM(dek).decrypt(nonce, encrypted[offset + 4 + header_size:], aad)


class EvidenceObjectStore(Protocol):
    def put_if_absent(self, object_key: str, content: bytes) -> None: ...
    def read(self, object_key: str) -> bytes: ...
    def delete(self, object_key: str) -> None: ...


class LocalEvidenceObjectStore:
    """Local development adapter. Production supplies Blob/S3 behind this protocol."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv("RETURN_EVIDENCE_OBJECT_ROOT") or ".data/return-evidence")

    def _path(self, object_key: str) -> Path:
        path = (self.root / object_key).resolve()
        root = self.root.resolve()
        if root not in path.parents:
            raise ValueError("invalid_return_evidence_object_key")
        return path

    def put_if_absent(self, object_key: str, content: bytes) -> None:
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(content)

    def read(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()

    def delete(self, object_key: str) -> None:
        self._path(object_key).unlink(missing_ok=True)


class AzureBlobEvidenceObjectStore:
    """Private Blob adapter authenticated only through Azure workload identity."""

    def __init__(self, *, account_url: str | None = None, container: str | None = None):
        account = str(account_url or os.getenv("AZURE_STORAGE_ACCOUNT_URL") or "").strip()
        container_name = str(
            container or os.getenv("RETURN_EVIDENCE_AZURE_CONTAINER")
            or os.getenv("AZURE_STORAGE_CONTAINER") or ""
        ).strip()
        if not account or not container_name:
            raise RuntimeError("return_evidence_azure_blob_configuration_required")
        from src.app.providers.azure import get_blob_container

        self._container = get_blob_container(account, container_name)

    def put_if_absent(self, object_key: str, content: bytes) -> None:
        self._container.get_blob_client(object_key).upload_blob(content, overwrite=False)

    def read(self, object_key: str) -> bytes:
        return bytes(self._container.get_blob_client(object_key).download_blob().readall())

    def delete(self, object_key: str) -> None:
        self._container.get_blob_client(object_key).delete_blob(delete_snapshots="include")


def evidence_object_store_from_env() -> EvidenceObjectStore:
    provider = str(
        os.getenv("RETURN_EVIDENCE_STORAGE_PROVIDER")
        or os.getenv("OBJECT_STORAGE_PROVIDER")
        or ""
    ).strip().lower()
    if provider in {"azure", "azure_blob", "azure-blob"}:
        return AzureBlobEvidenceObjectStore()
    if provider in {"local", "filesystem"}:
        return LocalEvidenceObjectStore()
    app_env = str(os.getenv("APP_ENV") or "dev").strip().lower()
    if app_env in {"prod", "production", "staging"}:
        raise RuntimeError("return_evidence_storage_provider_required")
    return LocalEvidenceObjectStore()


@dataclass(frozen=True)
class OrderVerification:
    status: str
    order_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ReturnAbuseAssessment:
    status: str
    reasons: tuple[str, ...] = ()
    claimant_window_count: int = 0
    order_window_count: int = 0


def assess_return_claim_abuse(
    db,
    *,
    tenant_id: str,
    claimant_id: str,
    order_id: str | None,
    evidence_digests: Iterable[str],
) -> ReturnAbuseAssessment:
    """Bound claim abuse without turning evidence heuristics into an automatic denial."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    claimant_count = int(db.execute(
        text(
            "SELECT COUNT(*) FROM return_claim WHERE tenant_id=:tenant "
            "AND claimant_id=:claimant AND created_at>=:cutoff"
        ),
        {"tenant": tenant_id, "claimant": claimant_id, "cutoff": cutoff},
    ).scalar() or 0)
    order_count = 0
    if order_id:
        order_count = int(db.execute(
            text(
                "SELECT COUNT(*) FROM return_claim WHERE tenant_id=:tenant "
                "AND claimant_id=:claimant AND order_id=:order_id AND created_at>=:cutoff"
            ),
            {
                "tenant": tenant_id, "claimant": claimant_id,
                "order_id": order_id, "cutoff": cutoff,
            },
        ).scalar() or 0)
    hard_limit = max(2, int(os.getenv("RETURN_CLAIM_HARD_LIMIT_24H", "20")))
    if claimant_count >= hard_limit:
        raise PermissionError("return_claim_velocity_limit_exceeded")
    reasons: list[str] = []
    if claimant_count >= max(1, int(os.getenv("RETURN_CLAIM_REVIEW_LIMIT_24H", "5"))):
        reasons.append("claimant_velocity_review")
    if order_id and order_count >= max(1, int(os.getenv("RETURN_ORDER_REVIEW_LIMIT_24H", "3"))):
        reasons.append("order_velocity_review")
    digests = sorted({str(value) for value in evidence_digests if str(value)})
    if digests:
        placeholders = ",".join(f":digest_{index}" for index in range(len(digests)))
        params: dict[str, Any] = {
            "tenant": tenant_id, "claimant": claimant_id,
            **{f"digest_{index}": value for index, value in enumerate(digests)},
        }
        duplicate = db.execute(
            text(
                "SELECT 1 FROM return_evidence_object e JOIN return_claim c ON c.id=e.claim_id "
                "WHERE e.tenant_id=:tenant AND c.claimant_id=:claimant "
                f"AND e.sha256 IN ({placeholders}) LIMIT 1"
            ),
            params,
        ).fetchone()
        if duplicate:
            reasons.append("duplicate_evidence_review")
    return ReturnAbuseAssessment(
        status="review_required" if reasons else "allowed",
        reasons=tuple(sorted(set(reasons))),
        claimant_window_count=claimant_count,
        order_window_count=order_count,
    )


def verify_owned_order(
    db,
    *,
    tenant_id: str,
    claimant_id: str,
    sku: str,
    order_id: str | None = None,
) -> OrderVerification:
    """Verify ownership without disclosing whether another tenant/buyer owns the ID."""
    try:
        params: dict[str, Any] = {"tenant": tenant_id, "claimant": claimant_id}
        where = "o.tenant_id=:tenant AND o.customer_id=:claimant"
        if order_id:
            where += " AND o.id=:order_id"
            params["order_id"] = str(order_id)
        rows = db.execute(
            text(
                "SELECT o.id, d.line_items FROM orders o "
                "LEFT JOIN draft_orders d ON d.id=o.draft_order_id AND d.tenant_id=o.tenant_id "
                f"WHERE {where} ORDER BY o.created_at DESC LIMIT 50"
            ),
            params,
        ).fetchall()
    except Exception as exc:
        return OrderVerification("source_unavailable", detail=type(exc).__name__)

    wanted = str(sku or "").strip().upper()
    for row in rows:
        try:
            items = json.loads(row[1]) if row[1] else []
        except (TypeError, json.JSONDecodeError):
            items = []
        if any(
            str(item.get("sku") or "").strip().upper() == wanted
            for item in items if isinstance(item, dict)
        ):
            return OrderVerification("found", order_id=str(row[0]), detail="authenticated_order_match")
    return OrderVerification("not_found", detail="no_authenticated_order_match")


def _audit(
    db,
    *,
    tenant_id: str,
    claim_id: str,
    action: str,
    actor_id: str,
    purpose: str,
    evidence_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not actor_id or not purpose:
        raise ValueError("return_evidence_audit_actor_and_purpose_required")
    db.execute(
        text(
            "INSERT INTO return_evidence_access_audit "
            "(id,tenant_id,claim_id,evidence_id,action,actor_id,purpose,metadata_json,created_at) "
            "VALUES (:id,:tenant,:claim,:evidence,:action,:actor,:purpose,:metadata,:created)"
        ),
        {
            "id": str(uuid.uuid4()), "tenant": tenant_id, "claim": claim_id,
            "evidence": evidence_id, "action": action, "actor": actor_id,
            "purpose": purpose, "metadata": json.dumps(metadata or {}, sort_keys=True),
            "created": _now(),
        },
    )


def _append_event(
    db,
    *,
    tenant_id: str,
    claim_id: str,
    event_type: str,
    from_status: str | None,
    to_status: str,
    actor_type: str,
    actor_id: str,
    evidence_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    row = db.execute(
        text(
            "SELECT COALESCE(MAX(sequence),0) FROM return_claim_event "
            "WHERE tenant_id=:tenant AND claim_id=:claim"
        ),
        {"tenant": tenant_id, "claim": claim_id},
    ).fetchone()
    sequence = int((row or [0])[0] or 0) + 1
    now = _now()
    db.execute(
        text(
            "INSERT INTO return_claim_event "
            "(id,tenant_id,claim_id,sequence,event_type,from_status,to_status,actor_type,actor_id,"
            "evidence_ref,metadata_json,effective_at,observed_at,recorded_at) VALUES "
            "(:id,:tenant,:claim,:sequence,:event,:from_status,:to_status,:actor_type,:actor_id,"
            ":evidence,:metadata,:effective,:observed,:recorded)"
        ),
        {
            "id": str(uuid.uuid4()), "tenant": tenant_id, "claim": claim_id,
            "sequence": sequence, "event": event_type, "from_status": from_status,
            "to_status": to_status, "actor_type": actor_type, "actor_id": actor_id,
            "evidence": evidence_ref, "metadata": json.dumps(metadata or {}, sort_keys=True),
            "effective": now, "observed": now, "recorded": now,
        },
    )
    return sequence


def create_claim(
    db,
    *,
    tenant_id: str,
    claimant_id: str,
    sku: str,
    description: str,
    order_verification: OrderVerification,
    abuse_assessment: ReturnAbuseAssessment | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    claim_id = str(uuid.uuid4())
    trace_id = f"return-{claim_id}"
    status = "evidence_pending" if order_verification.status != "not_found" else "needs_info"
    now = _now()
    db.execute(
        text(
            "INSERT INTO return_claim "
            "(id,tenant_id,claimant_id,order_id,sku,status,status_version,description_sanitized,"
            "order_verification_status,abuse_status,abuse_reasons_json,trace_id,idempotency_key,"
            "created_at,updated_at) VALUES "
            "(:id,:tenant,:claimant,:order_id,:sku,:status,1,:description,:verification,:abuse_status,"
            ":abuse_reasons,:trace,:idem,:created,:updated)"
        ),
        {
            "id": claim_id, "tenant": tenant_id, "claimant": claimant_id,
            "order_id": order_verification.order_id, "sku": str(sku)[:160], "status": status,
            "description": str(description or "")[:4000], "verification": order_verification.status,
            "abuse_status": (abuse_assessment or ReturnAbuseAssessment("allowed")).status,
            "abuse_reasons": json.dumps(
                list((abuse_assessment or ReturnAbuseAssessment("allowed")).reasons)
            ),
            "trace": trace_id, "idem": str(idempotency_key or uuid.uuid4()),
            "created": now, "updated": now,
        },
    )
    _append_event(
        db, tenant_id=tenant_id, claim_id=claim_id, event_type="claim_received",
        from_status=None, to_status=status, actor_type="buyer", actor_id=claimant_id,
        metadata={
            "order_verification_status": order_verification.status,
            "abuse_status": (abuse_assessment or ReturnAbuseAssessment("allowed")).status,
            "abuse_reasons": list((abuse_assessment or ReturnAbuseAssessment("allowed")).reasons),
            "next_action": (
                "provide_order_reference_or_receipt" if order_verification.status == "not_found"
                else "retry_authoritative_order_source" if order_verification.status == "source_unavailable"
                else "inspect_evidence"
            ),
        },
    )
    return {"claim_id": claim_id, "trace_id": trace_id, "status": status}


def find_idempotent_claim(
    db, *, tenant_id: str, claimant_id: str, idempotency_key: str
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            "SELECT id FROM return_claim WHERE tenant_id=:tenant AND claimant_id=:claimant "
            "AND idempotency_key=:idem"
        ),
        {"tenant": tenant_id, "claimant": claimant_id, "idem": idempotency_key},
    ).fetchone()
    return get_claim(
        db, tenant_id=tenant_id, claim_id=str(row[0]), claimant_id=claimant_id
    ) if row else None


def store_encrypted_artifacts(
    db,
    *,
    tenant_id: str,
    claim_id: str,
    files: Iterable[dict[str, Any]],
    actor_id: str,
    store: EvidenceObjectStore | None = None,
) -> list[dict[str, Any]]:
    object_store = store or evidence_object_store_from_env()
    key_id, keys = _keyring()
    retention_days = max(1, int(os.getenv("RETURN_EVIDENCE_RETENTION_DAYS", "365")))
    retained_until = (datetime.now(timezone.utc) + timedelta(days=retention_days)).isoformat()
    stored: list[dict[str, Any]] = []
    for item in files:
        raw = item.get("bytes")
        if not isinstance(raw, bytes) or not raw:
            raise ValueError("return_evidence_file_empty")
        evidence_id = str(uuid.uuid4())
        digest = hashlib.sha256(raw).hexdigest()
        tenant_bucket = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
        object_key = f"{tenant_bucket}/{claim_id}/{evidence_id}.aesgcm"
        safe_name = _safe_name(str(item.get("filename") or "upload.bin"))
        media_type = str(item.get("content_type") or "application/octet-stream")[:160]
        aad = f"{tenant_id}\0{claim_id}\0{evidence_id}\0{digest}".encode("utf-8")
        ciphertext = _encrypt_envelope(raw, aad=aad, key_id=key_id, kek=keys[key_id])
        object_store.put_if_absent(object_key, ciphertext)
        db.execute(
            text(
                "INSERT INTO return_evidence_object "
                "(id,tenant_id,claim_id,object_key,sha256,media_type,original_name_sanitized,size_bytes,"
                "cipher,encryption_key_id,retention_until,legal_hold,created_at) VALUES "
                "(:id,:tenant,:claim,:object_key,:sha,:media,:name,:size,'AES-256-GCM+AES-KW',:key_id,:retention,0,:created)"
            ),
            {
                "id": evidence_id, "tenant": tenant_id, "claim": claim_id,
                "object_key": object_key, "sha": digest, "media": media_type,
                "name": safe_name, "size": len(raw), "key_id": key_id,
                "retention": retained_until, "created": _now(),
            },
        )
        _audit(
            db, tenant_id=tenant_id, claim_id=claim_id, evidence_id=evidence_id,
            action="encrypted_evidence_stored", actor_id=actor_id, purpose="return_claim_intake",
            metadata={"sha256": digest, "size_bytes": len(raw)},
        )
        stored.append({"evidence_id": evidence_id, "sha256": digest, "status": "pending"})
    return stored


def load_encrypted_artifact(
    db,
    *,
    tenant_id: str,
    claim_id: str,
    evidence_id: str,
    actor_id: str,
    purpose: str,
    store: EvidenceObjectStore | None = None,
) -> bytes:
    row = db.execute(
        text(
            "SELECT object_key,sha256,encryption_key_id FROM return_evidence_object "
            "WHERE id=:evidence AND claim_id=:claim AND tenant_id=:tenant"
        ),
        {"evidence": evidence_id, "claim": claim_id, "tenant": tenant_id},
    ).fetchone()
    if not row:
        raise LookupError("return_evidence_not_found")
    _, keys = _keyring()
    key_id = str(row[2])
    if key_id not in keys:
        raise RuntimeError("return_evidence_decryption_key_unavailable")
    encrypted = (store or evidence_object_store_from_env()).read(str(row[0]))
    aad = f"{tenant_id}\0{claim_id}\0{evidence_id}\0{row[1]}".encode("utf-8")
    raw = _decrypt_envelope(encrypted, aad=aad, key_id=key_id, kek=keys[key_id])
    if hashlib.sha256(raw).hexdigest() != str(row[1]):
        raise ValueError("return_evidence_digest_mismatch")
    _audit(
        db, tenant_id=tenant_id, claim_id=claim_id, evidence_id=evidence_id,
        action="read", actor_id=actor_id, purpose=purpose,
    )
    return raw


def set_evidence_legal_hold(
    db,
    *,
    tenant_id: str,
    claim_id: str,
    evidence_id: str,
    enabled: bool,
    actor_id: str,
    purpose: str,
) -> None:
    result = db.execute(
        text(
            "UPDATE return_evidence_object SET legal_hold=:enabled "
            "WHERE id=:evidence AND claim_id=:claim AND tenant_id=:tenant"
        ),
        {
            "enabled": bool(enabled), "evidence": evidence_id,
            "claim": claim_id, "tenant": tenant_id,
        },
    )
    if int(result.rowcount or 0) != 1:
        raise LookupError("return_evidence_not_found")
    _audit(
        db, tenant_id=tenant_id, claim_id=claim_id, evidence_id=evidence_id,
        action="legal_hold_enabled" if enabled else "legal_hold_disabled",
        actor_id=actor_id, purpose=purpose,
    )


def purge_expired_return_evidence(
    db,
    *,
    actor_id: str,
    purpose: str,
    now: datetime | None = None,
    store: EvidenceObjectStore | None = None,
) -> int:
    cutoff = (now or datetime.now(timezone.utc)).isoformat()
    rows = db.execute(
        text(
            "SELECT id,tenant_id,claim_id,object_key FROM return_evidence_object "
            "WHERE legal_hold=0 AND retention_until < :cutoff"
        ),
        {"cutoff": cutoff},
    ).fetchall()
    object_store = store or evidence_object_store_from_env()
    deleted = 0
    for row in rows:
        object_store.delete(str(row[3]))
        _audit(
            db, tenant_id=str(row[1]), claim_id=str(row[2]), evidence_id=str(row[0]),
            action="retention_deleted", actor_id=actor_id, purpose=purpose,
            metadata={"retention_cutoff": cutoff},
        )
        db.execute(
            text(
                "DELETE FROM return_evidence_object "
                "WHERE id=:evidence AND tenant_id=:tenant AND legal_hold=0"
            ),
            {"evidence": row[0], "tenant": row[1]},
        )
        deleted += 1
    return deleted


def queue_evidence_job(db, *, tenant_id: str, claim_id: str) -> str:
    job_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO return_evidence_job "
            "(id,tenant_id,claim_id,status,security_status,visual_status,attempts,created_at) "
            "VALUES (:id,:tenant,:claim,'queued','pending','pending',0,:created)"
        ),
        {"id": job_id, "tenant": tenant_id, "claim": claim_id, "created": _now()},
    )
    return job_id


def transition_claim(
    db,
    *,
    tenant_id: str,
    claim_id: str,
    to_status: str,
    actor_type: str,
    actor_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if to_status not in CLAIM_STATES:
        raise ValueError("invalid_return_claim_status")
    row = db.execute(
        text(
            "SELECT status,status_version FROM return_claim "
            "WHERE id=:claim AND tenant_id=:tenant"
        ),
        {"claim": claim_id, "tenant": tenant_id},
    ).fetchone()
    if not row:
        raise LookupError("return_claim_not_found")
    current, version = str(row[0]), int(row[1])
    if to_status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal_return_claim_transition:{current}:{to_status}")
    result = db.execute(
        text(
            "UPDATE return_claim SET status=:to_status,status_version=:next_version,updated_at=:updated "
            "WHERE id=:claim AND tenant_id=:tenant AND status_version=:version"
        ),
        {
            "to_status": to_status, "next_version": version + 1, "updated": _now(),
            "claim": claim_id, "tenant": tenant_id, "version": version,
        },
    )
    if int(result.rowcount or 0) != 1:
        raise RuntimeError("return_claim_concurrent_update")
    _append_event(
        db, tenant_id=tenant_id, claim_id=claim_id, event_type="claim_status_changed",
        from_status=current, to_status=to_status, actor_type=actor_type, actor_id=actor_id,
        metadata=metadata,
    )
    return {"claim_id": claim_id, "from_status": current, "status": to_status, "version": version + 1}


def list_claims(
    db,
    *,
    tenant_id: str,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return a bounded operator queue without leaking another tenant's claims."""
    if status and status not in CLAIM_STATES:
        raise ValueError("invalid_return_claim_status")
    params: dict[str, Any] = {
        "tenant": tenant_id,
        "limit": max(1, min(int(limit), 200)),
    }
    status_clause = ""
    if status:
        status_clause = " AND c.status=:status"
        params["status"] = status
    rows = db.execute(
        text(
            "SELECT c.id,c.order_id,c.sku,c.status,c.status_version,c.order_verification_status,"
            "c.abuse_status,c.abuse_reasons_json,c.trace_id,c.created_at,c.updated_at,"
            "j.status,j.security_status,j.visual_status "
            "FROM return_claim c LEFT JOIN return_evidence_job j "
            "ON j.claim_id=c.id AND j.tenant_id=c.tenant_id "
            f"WHERE c.tenant_id=:tenant{status_clause} "
            "ORDER BY c.updated_at DESC LIMIT :limit"
        ),
        params,
    ).fetchall()
    return [
        {
            "claim_id": row[0], "order_id": row[1], "sku": row[2], "status": row[3],
            "status_version": row[4], "order_verification_status": row[5],
            "abuse_status": row[6], "abuse_reasons": json.loads(row[7] or "[]"),
            "trace_id": row[8], "created_at": row[9], "updated_at": row[10],
            "evidence_job": ({
                "status": row[11], "security_status": row[12], "visual_status": row[13],
            } if row[11] else None),
        }
        for row in rows
    ]


def list_claim_evidence(db, *, tenant_id: str, claim_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            "SELECT id,sha256,media_type,original_name_sanitized,size_bytes,cipher,"
            "encryption_key_id,retention_until,legal_hold,created_at "
            "FROM return_evidence_object WHERE tenant_id=:tenant AND claim_id=:claim "
            "ORDER BY created_at"
        ),
        {"tenant": tenant_id, "claim": claim_id},
    ).fetchall()
    return [
        {
            "evidence_id": row[0], "sha256": row[1], "media_type": row[2],
            "filename": row[3], "size_bytes": row[4], "cipher": row[5],
            "encryption_key_id": row[6], "retention_until": row[7],
            "legal_hold": bool(row[8]), "created_at": row[9],
        }
        for row in rows
    ]


def get_claim(db, *, tenant_id: str, claim_id: str, claimant_id: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"tenant": tenant_id, "claim": claim_id}
    owner = ""
    if claimant_id is not None:
        owner = " AND claimant_id=:claimant"
        params["claimant"] = claimant_id
    row = db.execute(
        text(
            "SELECT id,order_id,sku,status,status_version,description_sanitized,"
            "order_verification_status,abuse_status,abuse_reasons_json,trace_id,created_at,updated_at "
            "FROM return_claim "
            f"WHERE tenant_id=:tenant AND id=:claim{owner}"
        ),
        params,
    ).fetchone()
    if not row:
        raise LookupError("return_claim_not_found")
    events = db.execute(
        text(
            "SELECT sequence,event_type,from_status,to_status,actor_type,evidence_ref,metadata_json,"
            "effective_at,observed_at,recorded_at FROM return_claim_event "
            "WHERE tenant_id=:tenant AND claim_id=:claim ORDER BY sequence"
        ),
        {"tenant": tenant_id, "claim": claim_id},
    ).fetchall()
    job = db.execute(
        text(
            "SELECT id,status,security_status,visual_status,attempts,last_error FROM return_evidence_job "
            "WHERE tenant_id=:tenant AND claim_id=:claim"
        ),
        {"tenant": tenant_id, "claim": claim_id},
    ).fetchone()
    return {
        "claim_id": row[0], "order_id": row[1], "sku": row[2], "status": row[3],
        "status_version": row[4], "description": row[5], "order_verification_status": row[6],
        "abuse_status": row[7], "abuse_reasons": json.loads(row[8] or "[]"),
        "trace_id": row[9], "created_at": row[10], "updated_at": row[11],
        "evidence_job": ({
            "job_id": job[0], "status": job[1], "security_status": job[2],
            "visual_status": job[3], "attempts": job[4], "last_error": job[5],
        } if job else None),
        "evidence": list_claim_evidence(db, tenant_id=tenant_id, claim_id=claim_id),
        "timeline": [
            {
                "sequence": event[0], "event_type": event[1], "from_status": event[2],
                "to_status": event[3], "actor_type": event[4], "evidence_ref": event[5],
                "metadata": json.loads(event[6] or "{}"), "effective_at": event[7],
                "observed_at": event[8], "recorded_at": event[9],
            }
            for event in events
        ],
    }
