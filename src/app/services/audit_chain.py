from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
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


def _anchor_key() -> str:
    return str(
        os.getenv("AUDIT_CHAIN_ANCHOR_HMAC_KEY", os.getenv("WEBHOOK_SECRET", "shopsquire-audit-anchor-dev"))
        or "shopsquire-audit-anchor-dev"
    )


def _anchor_path() -> Path:
    return Path(os.getenv("AUDIT_CHAIN_ANCHOR_PATH", "runs/audit_chain_anchors.log"))


def _anchor_signature(payload: str) -> str:
    return hmac.new(_anchor_key().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _append_anchor_record(merkle_root: str) -> None:
    p = _anchor_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = _now()
    rid = f"anchor-{uuid.uuid4().hex[:12]}"
    prev_sig = ""
    if p.exists():
        try:
            last = p.read_text(encoding="utf-8").strip().splitlines()[-1]
            prev = json.loads(last)
            prev_sig = str(prev.get("signature") or "")
        except Exception:
            prev_sig = ""
    payload = f"{rid}|{ts}|{merkle_root}|{prev_sig}"
    rec = {
        "id": rid,
        "created_at": ts,
        "merkle_root": merkle_root,
        "prev_signature": prev_sig,
        "signature": _anchor_signature(payload),
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_latest_anchor() -> Dict[str, Any] | None:
    p = _anchor_path()
    if not p.exists():
        return None
    try:
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None


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
            try:
                _append_anchor_record(merkle_root)
            except Exception:
                pass
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
    anchor = _read_latest_anchor()
    anchor_status = {"present": bool(anchor), "ok": None}
    if anchor:
        try:
            payload = f"{anchor.get('id')}|{anchor.get('created_at')}|{anchor.get('merkle_root')}|{anchor.get('prev_signature') or ''}"
            sig_ok = hmac.compare_digest(str(anchor.get("signature") or ""), _anchor_signature(payload))
            head_ok = str(anchor.get("merkle_root") or "") == str(prev or "")
            anchor_status = {"present": True, "ok": bool(sig_ok and head_ok), "signature_ok": bool(sig_ok), "head_match": bool(head_ok)}
            if not (sig_ok and head_ok):
                return {"ok": False, "checked": checked, "head": prev, "reason": "anchor_mismatch", "anchor": anchor_status}
        except Exception:
            return {"ok": False, "checked": checked, "head": prev, "reason": "anchor_verify_failed", "anchor": {"present": True, "ok": False}}
    return {"ok": True, "checked": checked, "head": prev, "anchor": anchor_status}
