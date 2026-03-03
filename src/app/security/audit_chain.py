"""C01 — Cryptographic hash chain for audit log tamper-evidence.

Each DecisionAudit row includes:
- `prev_hash`: SHA-256 of the preceding record's `record_hash`.
- `record_hash`: SHA-256(id || decision_id || action || actor || metadata || created_at || prev_hash).

Verification walks the chain and re-computes each hash.  Any mismatch proves
tampering of the row *or* a preceding row.  An external anchor (daily digest)
can be published to an immutable store (S3 Object Lock, blockchain, etc.)
to detect bulk rewrite attacks.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHAIN_SECRET = None


def _get_chain_secret() -> str:
    global _CHAIN_SECRET
    if _CHAIN_SECRET is None:
        _CHAIN_SECRET = os.getenv("AUDIT_CHAIN_SECRET", "shopsquire-audit-chain-hmac-key")
    return _CHAIN_SECRET


def compute_record_hash(
    *,
    record_id: str,
    decision_id: str,
    action: str,
    actor: str | None,
    metadata: str | None,
    created_at: str | None,
    prev_hash: str | None,
) -> str:
    """Compute a deterministic SHA-256 for a single audit row."""
    canonical = "|".join([
        str(record_id or ""),
        str(decision_id or ""),
        str(action or ""),
        str(actor or ""),
        str(metadata or ""),
        str(created_at or ""),
        str(prev_hash or "genesis"),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_latest_hash(db_session_ctx) -> str | None:
    """Fetch the record_hash of the most recent DecisionAudit row."""
    try:
        from sqlalchemy import text
        row = db_session_ctx.execute(
            text("SELECT record_hash FROM decision_audits ORDER BY created_at DESC, id DESC LIMIT 1")
        ).fetchone()
        if row:
            return str(row[0]) if row[0] else None
    except Exception:
        pass
    return None


def chain_new_record(
    db_session_ctx,
    *,
    record_id: str,
    decision_id: str,
    action: str,
    actor: str | None = None,
    metadata: str | None = None,
    created_at: str | None = None,
) -> Dict[str, str]:
    """Compute prev_hash + record_hash for a new audit row.

    Returns dict with keys ``prev_hash`` and ``record_hash`` to be stored on the row.
    """
    prev = get_latest_hash(db_session_ctx)
    rh = compute_record_hash(
        record_id=record_id,
        decision_id=decision_id,
        action=action,
        actor=actor,
        metadata=metadata,
        created_at=created_at,
        prev_hash=prev,
    )
    return {"prev_hash": prev or "genesis", "record_hash": rh}


def verify_chain(db_session_ctx, *, limit: int = 1000) -> Dict[str, Any]:
    """Walk the audit chain and verify hash integrity.

    Returns summary with ``valid``, ``checked``, ``first_broken_id``.
    """
    from sqlalchemy import text

    rows = db_session_ctx.execute(
        text(
            "SELECT id, decision_id, action, actor, metadata, created_at, prev_hash, record_hash "
            "FROM decision_audits ORDER BY created_at ASC, id ASC LIMIT :lim"
        ),
        {"lim": limit},
    ).fetchall()

    checked = 0
    prev_expected: str | None = None
    for row in rows:
        rid, did, action, actor, meta, cat, ph, rh = row
        if rh is None:
            # Legacy row without hash — skip but note
            prev_expected = None
            continue
        # Verify prev_hash matches previous row's record_hash
        if prev_expected is not None and str(ph or "") != prev_expected:
            return {"valid": False, "checked": checked, "first_broken_id": rid, "reason": "prev_hash_mismatch"}
        expected_rh = compute_record_hash(
            record_id=str(rid),
            decision_id=str(did),
            action=str(action or ""),
            actor=str(actor) if actor else None,
            metadata=str(meta) if meta else None,
            created_at=str(cat) if cat else None,
            prev_hash=str(ph) if ph else None,
        )
        if expected_rh != str(rh):
            return {"valid": False, "checked": checked, "first_broken_id": rid, "reason": "record_hash_mismatch"}
        prev_expected = str(rh)
        checked += 1

    return {"valid": True, "checked": checked, "first_broken_id": None, "reason": None}


def daily_digest(db_session_ctx) -> str:
    """Compute a daily SHA-256 digest over all record_hashes — suitable for external anchoring."""
    from sqlalchemy import text
    rows = db_session_ctx.execute(
        text("SELECT record_hash FROM decision_audits WHERE record_hash IS NOT NULL ORDER BY created_at ASC, id ASC")
    ).fetchall()
    h = hashlib.sha256()
    for (rh,) in rows:
        h.update(str(rh or "").encode("utf-8"))
    return h.hexdigest()
