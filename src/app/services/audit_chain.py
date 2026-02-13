from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.app.models.db import db_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_audit_chain_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS audit_log_chain (
                        id TEXT PRIMARY KEY,
                        source_type TEXT NOT NULL,
                        source_id TEXT,
                        payload_hash TEXT NOT NULL,
                        prev_hash TEXT,
                        merkle_root TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
            try:
                db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_log_chain_created ON audit_log_chain(created_at)"))
            except Exception:
                pass
            db.commit()
    except Exception:
        pass


def _sha256(text_value: str) -> str:
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def append_audit_chain_event(*, source_type: str, source_id: str | None, payload: Dict[str, Any]) -> Optional[str]:
    ensure_audit_chain_table()
    payload_json = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    payload_hash = _sha256(payload_json)
    try:
        with db_session() as db:
            prev = db.execute(
                text("SELECT merkle_root FROM audit_log_chain ORDER BY created_at DESC LIMIT 1")
            ).fetchone()
            prev_hash = str(prev[0]) if prev and prev[0] else ""
            merkle_root = _sha256(f"{prev_hash}:{payload_hash}")
            row_id = str(uuid.uuid4())
            db.execute(
                text(
                    """
                    INSERT INTO audit_log_chain (
                        id, source_type, source_id, payload_hash, prev_hash, merkle_root, created_at
                    ) VALUES (
                        :id, :source_type, :source_id, :payload_hash, :prev_hash, :merkle_root, :created_at
                    )
                    """
                ),
                {
                    "id": row_id,
                    "source_type": source_type,
                    "source_id": source_id,
                    "payload_hash": payload_hash,
                    "prev_hash": prev_hash or None,
                    "merkle_root": merkle_root,
                    "created_at": _now(),
                },
            )
            db.commit()
            return merkle_root
    except Exception:
        return None


def verify_audit_chain(limit: int = 1000) -> Dict[str, Any]:
    ensure_audit_chain_table()
    limit = max(1, min(int(limit or 1000), 10000))
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, payload_hash, prev_hash, merkle_root, created_at
                FROM audit_log_chain
                ORDER BY created_at ASC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()
    prev = ""
    checked = 0
    for r in rows or []:
        payload_hash = str(r[1] or "")
        prev_hash = str(r[2] or "")
        merkle = str(r[3] or "")
        expected = _sha256(f"{prev}:{payload_hash}")
        if prev_hash != (prev or ""):
            return {"ok": False, "checked": checked, "failed_id": r[0], "reason": "prev_hash_mismatch"}
        if merkle != expected:
            return {"ok": False, "checked": checked, "failed_id": r[0], "reason": "merkle_mismatch"}
        prev = merkle
        checked += 1
    return {"ok": True, "checked": checked, "head": prev}
