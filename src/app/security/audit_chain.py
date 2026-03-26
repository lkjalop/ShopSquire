"""C01 — Cryptographic hash chain for audit log tamper-evidence.

Each DecisionAudit row includes:
- `prev_hash`: SHA-256 of the preceding record's `record_hash`.
- `record_hash`: SHA-256(id || decision_id || action || actor || metadata || created_at || prev_hash).

Verification walks the chain and re-computes each hash.  Any mismatch proves
tampering of the row *or* a preceding row.  An external anchor (daily digest)
can be published to an immutable store (S3 Object Lock, blockchain, etc.)
to detect bulk rewrite attacks.
"""
"""C01 — Cryptographic hash chain for audit log tamper-evidence (extended).

IT-PREV-04 additions
--------------------
WORM archive: every new audit record is appended (O_APPEND) to a local
append-only file whose path is set by ``AUDIT_CHAIN_WORM_ARCHIVE_PATH``.
Mount that path on immutable / WORM-capable storage in production
(e.g. AWS S3 Object Lock via a sidecar, a WORM NAS mount, or GCS bucket
with retention policy).

The append-only nature means even a DBA who can DELETE from the DB table
cannot retroactively remove the WORM entry — creating detectable divergence.
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

_WEAK_DEFAULTS = frozenset({
    "shopsquire-audit-chain-hmac-key",
    "dev-only-do-not-use-in-prod",
    "",
})


def _get_chain_secret() -> str:
    """Return the HMAC secret used for audit-chain integrity.

    Fails closed (raises) in non-local environments when the secret is absent
    or matches a known weak default — preserving tamper-evidence guarantees.
    """
    global _CHAIN_SECRET
    if _CHAIN_SECRET is None:
        raw = str(os.getenv("AUDIT_CHAIN_SECRET") or "")
        env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
        is_prod_like = env not in ("local", "dev", "development", "test", "testing")

        if not raw or raw in _WEAK_DEFAULTS:
            if is_prod_like:
                raise RuntimeError(
                    "AUDIT_CHAIN_SECRET is not set or uses a known weak default. "
                    "Set a strong random secret (≥32 bytes) in your environment before starting. "
                    "Without this the audit chain HMAC is meaningless and any attacker "
                    "with source access can forge audit records."
                )
            logger.warning(
                "AUDIT_CHAIN_SECRET not set — using insecure dev placeholder. "
                "This is only acceptable in local/dev/test environments."
            )
            raw = "dev-only-do-not-use-in-prod"

        if len(raw) < 32 and is_prod_like:
            raise RuntimeError(
                f"AUDIT_CHAIN_SECRET is only {len(raw)} characters. "
                "Use at least 32 random bytes (e.g. openssl rand -hex 32)."
            )

        _CHAIN_SECRET = raw
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


def _worm_append(entry: Dict[str, Any]) -> None:
    """IT-PREV-04 — Append a JSON line to the WORM archive file.

    Uses ``os.O_APPEND`` which is atomic on POSIX for writes ≤ PIPE_BUF
    (~4 KB).  The file handle is opened and closed on every call to avoid
    holding file descriptors across long-lived processes.

    If the path is unset or the write fails, we log a warning but never
    raise — the DB record is the primary store; the WORM file is a secondary
    tamper-evidence layer.
    """
    worm_path = str(os.getenv("AUDIT_CHAIN_WORM_ARCHIVE_PATH", "") or "").strip()
    if not worm_path:
        return
    try:
        line = json.dumps(entry, separators=(",", ":"), default=str) + "\n"
        # O_CREAT | O_APPEND | O_WRONLY — never truncates, always appends
        fd = os.open(worm_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as exc:
        logger.warning("audit_chain worm_append_failed path=%s: %s", worm_path, exc)


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

    Returns dict with keys ``prev_hash`` and ``record_hash`` to be stored on
    the row.  Also appends to the WORM archive (IT-PREV-04).
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
    result = {"prev_hash": prev or "genesis", "record_hash": rh}

    # IT-PREV-04: append to WORM archive (non-blocking, never raises)
    _worm_append({
        "id":          record_id,
        "decision_id": decision_id,
        "action":      action,
        "actor":       actor,
        "prev_hash":   prev or "genesis",
        "record_hash": rh,
        "created_at":  created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    return result


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
