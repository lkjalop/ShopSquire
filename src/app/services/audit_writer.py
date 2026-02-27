"""Helper to insert DecisionAudit rows with hash-chain tamper-evidence."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def insert_audit_row(
    conn,
    *,
    decision_id: str,
    action: str,
    actor: str | None = None,
    metadata: Dict[str, Any] | str | None = None,
    record_id: str | None = None,
) -> str:
    """Insert a DecisionAudit row with hash-chain fields.

    Uses the provided connection (engine.connect() or session) to compute the
    prev_hash from the latest row, then inserts with record_hash + prev_hash.
    Returns the generated row id.
    """
    rid = record_id or str(uuid.uuid4())
    meta_str = json.dumps(metadata) if isinstance(metadata, dict) else (metadata or "")

    # Fetch latest record_hash for chain
    prev_hash = "genesis"
    try:
        row = conn.execute(
            text("SELECT record_hash FROM decision_audits WHERE record_hash IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1")
        ).fetchone()
        if row and row[0]:
            prev_hash = str(row[0])
    except Exception:
        pass

    # Compute record hash
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        from src.app.security.audit_chain import compute_record_hash
        rh = compute_record_hash(
            record_id=rid,
            decision_id=decision_id,
            action=action,
            actor=actor,
            metadata=meta_str,
            created_at=created_at,
            prev_hash=prev_hash,
        )
    except Exception:
        rh = None

    conn.execute(
        text(
            "INSERT INTO decision_audits (id, decision_id, action, actor, metadata, created_at, record_hash, prev_hash) "
            "VALUES (:id, :decision_id, :action, :actor, :metadata, :created_at, :record_hash, :prev_hash)"
        ),
        {
            "id": rid,
            "decision_id": decision_id,
            "action": action,
            "actor": actor,
            "metadata": meta_str,
            "created_at": created_at,
            "record_hash": rh,
            "prev_hash": prev_hash,
        },
    )
    return rid
