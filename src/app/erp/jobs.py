from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.erp.connectors.base import InventoryConnector, InventoryRecord
from src.app.erp.connectors.netsuite import NetSuiteConnector, NetSuiteCustomer, NetSuiteSalesOrder
from src.app.erp.sync import sync_inventory
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
            db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_erp_outbound_pending ON erp_outbound_queue(provider, status, created_at)"
                )
            )
            db.commit()
    except Exception:
        pass


class _SnapshotConnector(InventoryConnector):
    def __init__(self, rows: List[InventoryRecord], name: str) -> None:
        self._rows = list(rows or [])
        self._name = name

    def name(self) -> str:
        return self._name

    def fetch_inventory(self, *, tenant_id: str | None = None) -> List[InventoryRecord]:
        _ = tenant_id
        return list(self._rows)

    def health(self) -> Dict[str, Any]:
        return {"ok": True}


def run_netsuite_delta_sync(*, tenant_id: str | None, dry_run: bool = True, upsert_products: bool = False, limit: int = 2000) -> Dict[str, Any]:
    ns = NetSuiteConnector()
    prev_cursor = ns.get_cursor(tenant_id=tenant_id, entity_type="inventory")
    rows, next_cursor = ns.fetch_inventory_delta(cursor=prev_cursor, tenant_id=tenant_id, limit=limit)
    c = _SnapshotConnector(rows=rows, name="netsuite")
    out = sync_inventory(connector=c, tenant_id=tenant_id, dry_run=dry_run, upsert_products=upsert_products)
    if not dry_run and not out.get("error") and next_cursor != prev_cursor:
        ns.set_cursor(tenant_id=tenant_id, entity_type="inventory", cursor_value=next_cursor)
    out["cursor"] = {"previous": prev_cursor, "next": (next_cursor if not dry_run else prev_cursor)}
    out["delta_count"] = len(rows or [])
    return out


def enqueue_netsuite_outbound(*, tenant_id: str | None, entity_type: str, payload: Dict[str, Any], max_attempts: int = 3) -> Dict[str, Any]:
    _ensure_outbound_table()
    qid = f"erpq-{uuid.uuid4().hex}"
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO erp_outbound_queue
                (id, tenant_id, provider, entity_type, payload_json, status, attempts, max_attempts, updated_at)
                VALUES
                (:id, :tenant_id, 'netsuite', :entity_type, :payload_json, 'pending', 0, :max_attempts, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": qid,
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "payload_json": json.dumps(payload or {}, ensure_ascii=False),
                "max_attempts": int(max(1, max_attempts)),
            },
        )
        db.commit()
    return {"id": qid, "status": "pending"}


def run_netsuite_outbound_sync(*, tenant_id: str | None = None, limit: int = 100) -> Dict[str, Any]:
    _ensure_outbound_table()
    ns = NetSuiteConnector()
    lim = max(1, min(int(limit or 100), 1000))
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, entity_type, payload_json, attempts, max_attempts
                FROM erp_outbound_queue
                WHERE provider = 'netsuite'
                  AND status IN ('pending', 'retry')
                  AND (:tenant_id IS NULL OR tenant_id = :tenant_id)
                ORDER BY created_at ASC
                LIMIT :lim
                """
            ),
            {"tenant_id": tenant_id, "lim": lim},
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
            if entity_type == "customer":
                res = ns.push_customer(
                    NetSuiteCustomer(
                        external_id=str(payload.get("external_id") or payload.get("id") or ""),
                        email=str(payload.get("email") or ""),
                        name=str(payload.get("name") or ""),
                    )
                )
                ok = bool(res.get("ok"))
                err = str(res.get("detail") or "")
            elif entity_type in ("sales_order", "order"):
                res = ns.push_sales_order(
                    NetSuiteSalesOrder(
                        external_id=str(payload.get("external_id") or payload.get("id") or ""),
                        customer_external_id=str(payload.get("customer_external_id") or ""),
                        currency=str(payload.get("currency") or "USD"),
                        total_cents=int(payload.get("total_cents") or 0),
                        line_items=list(payload.get("line_items") or []),
                    )
                )
                ok = bool(res.get("ok"))
                err = str(res.get("detail") or "")
            else:
                ok = False
                err = "unsupported_entity_type"
        except Exception as exc:
            ok = False
            err = str(exc)
        with db_session() as db:
            if ok:
                db.execute(
                    text(
                        "UPDATE erp_outbound_queue SET status='sent', attempts=:attempts, last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=:id"
                    ),
                    {"id": rid, "attempts": attempts},
                )
                db.commit()
                sent += 1
            else:
                if attempts >= max_attempts:
                    db.execute(
                        text(
                            "UPDATE erp_outbound_queue SET status='failed', attempts=:attempts, last_error=:err, updated_at=CURRENT_TIMESTAMP WHERE id=:id"
                        ),
                        {"id": rid, "attempts": attempts, "err": err[:500]},
                    )
                    db.commit()
                    failed += 1
                else:
                    db.execute(
                        text(
                            "UPDATE erp_outbound_queue SET status='retry', attempts=:attempts, last_error=:err, updated_at=CURRENT_TIMESTAMP WHERE id=:id"
                        ),
                        {"id": rid, "attempts": attempts, "err": err[:500]},
                    )
                    db.commit()
                    retrying += 1
    return {"processed": len(rows or []), "sent": sent, "failed": failed, "retrying": retrying}

