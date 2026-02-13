from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from sqlalchemy import text

from src.app.erp.provider_registry import load_provider
from src.app.models.db import db_session


def _ensure_outbound_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS erp_outbound_queue (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT,
                        provider TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        max_attempts INTEGER NOT NULL DEFAULT 3,
                        last_error TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(text("CREATE INDEX IF NOT EXISTS idx_erp_outbound_pending ON erp_outbound_queue(provider, status, created_at)"))
            db.commit()
    except Exception:
        pass


def enqueue_outbound(*, provider: str, tenant_id: str | None, entity_type: str, payload: Dict[str, Any], max_attempts: int = 3) -> Dict[str, Any]:
    _ensure_outbound_table()
    qid = f"erpq-{uuid.uuid4().hex}"
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO erp_outbound_queue
                (id, tenant_id, provider, entity_type, payload_json, status, attempts, max_attempts, updated_at)
                VALUES
                (:id, :tenant_id, :provider, :entity_type, :payload_json, 'pending', 0, :max_attempts, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": qid,
                "tenant_id": tenant_id,
                "provider": provider,
                "entity_type": entity_type,
                "payload_json": json.dumps(payload or {}, ensure_ascii=False),
                "max_attempts": int(max(1, max_attempts)),
            },
        )
        db.commit()
    return {"id": qid, "status": "pending"}


def run_outbound(*, provider: str, tenant_id: str | None = None, limit: int = 100) -> Dict[str, Any]:
    _ensure_outbound_table()
    conn = load_provider(provider)
    lim = max(1, min(int(limit or 100), 1000))
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, entity_type, payload_json, attempts, max_attempts
                FROM erp_outbound_queue
                WHERE provider = :provider
                  AND status IN ('pending', 'retry')
                  AND (:tenant_id IS NULL OR tenant_id = :tenant_id)
                ORDER BY created_at ASC
                LIMIT :lim
                """
            ),
            {"provider": provider, "tenant_id": tenant_id, "lim": lim},
        ).fetchall()
    sent = 0
    failed = 0
    retrying = 0
    for r in rows or []:
        rid = str(r[0])
        entity_type = str(r[1] or "").lower()
        try:
            payload = json.loads(r[2]) if r[2] else {}
        except Exception:
            payload = {}
        attempts = int(r[3] or 0) + 1
        max_attempts = int(r[4] or 3)
        ok = False
        err = ""
        try:
            res = conn.push_entity(entity_type, payload)
            ok = bool((res or {}).get("ok"))
            err = str((res or {}).get("detail") or "")
        except Exception as exc:
            ok = False
            err = str(exc)
        with db_session() as db:
            if ok:
                db.execute(
                    text("UPDATE erp_outbound_queue SET status='sent', attempts=:attempts, last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
                    {"id": rid, "attempts": attempts},
                )
                db.commit()
                sent += 1
            else:
                if attempts >= max_attempts:
                    db.execute(
                        text("UPDATE erp_outbound_queue SET status='failed', attempts=:attempts, last_error=:err, updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
                        {"id": rid, "attempts": attempts, "err": err[:500]},
                    )
                    db.commit()
                    failed += 1
                else:
                    db.execute(
                        text("UPDATE erp_outbound_queue SET status='retry', attempts=:attempts, last_error=:err, updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
                        {"id": rid, "attempts": attempts, "err": err[:500]},
                    )
                    db.commit()
                    retrying += 1
    return {"processed": len(rows or []), "sent": sent, "failed": failed, "retrying": retrying}

