from __future__ import annotations

import uuid
from typing import Any, Dict, List, Tuple

from sqlalchemy import text


def ensure_inventory_reservation_table(db) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS inventory_reservations (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            qty INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """))


def reserve_inventory_for_order(
    db,
    *,
    order_id: str,
    line_items: List[Dict[str, Any]],
    strict_untracked: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    """Reserve tracked stock using an atomic decrement for each order line."""
    ensure_inventory_reservation_table(db)
    shortages: list[dict[str, Any]] = []
    reserved: list[dict[str, Any]] = []
    for item in line_items or []:
        sku = str(item.get("sku") or "").strip()
        qty = int(item.get("quantity") or 0)
        if not sku or qty <= 0:
            continue
        try:
            row = db.execute(text("""
                SELECT id, qty, status
                FROM inventory_reservations
                WHERE order_id = :order_id AND sku = :sku
                ORDER BY created_at DESC
                LIMIT 1
            """), {"order_id": order_id, "sku": sku}).fetchone()
        except Exception:
            row = None
        if row and str(row[2] or "").lower() == "reserved":
            reserved.append({"sku": sku, "qty": int(row[1] or qty), "idempotent": True})
            continue

        try:
            inventory = db.execute(text("""
                SELECT i.id, i.stock
                FROM inventory i
                JOIN products p ON p.id = i.product_id
                WHERE p.sku = :sku
                ORDER BY i.updated_at DESC
                LIMIT 1
            """), {"sku": sku}).fetchone()
        except Exception:
            inventory = None

        if not inventory:
            if strict_untracked:
                shortages.append({"sku": sku, "requested_qty": qty, "reason": "untracked_sku"})
            continue
        inventory_id = str(inventory[0])
        stock = int(inventory[1] or 0)
        if stock < qty:
            shortages.append({
                "sku": sku,
                "requested_qty": qty,
                "available": stock,
                "reason": "insufficient_stock",
            })
            continue

        result = db.execute(
            text("UPDATE inventory SET stock = stock - :qty, updated_at = CURRENT_TIMESTAMP "
                 "WHERE id = :id AND stock >= :qty"),
            {"id": inventory_id, "qty": qty},
        )
        if int(getattr(result, "rowcount", 0) or 0) <= 0:
            shortages.append({
                "sku": sku,
                "requested_qty": qty,
                "available": stock,
                "reason": "race_or_negative_guard",
            })
            continue

        db.execute(text("""
            INSERT INTO inventory_reservations
                (id, order_id, sku, qty, status, created_at, updated_at)
            VALUES (:id, :order_id, :sku, :qty, 'reserved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"id": str(uuid.uuid4()), "order_id": order_id, "sku": sku, "qty": qty})
        reserved.append({"sku": sku, "qty": qty, "idempotent": False})

    if shortages:
        return False, {"shortages": shortages, "reserved": reserved}
    return True, {"reserved": reserved}


def release_inventory_for_order(db, *, order_id: str) -> Dict[str, Any]:
    """Release reserved stock once. Database failures propagate for transaction rollback."""
    ensure_inventory_reservation_table(db)
    rows = db.execute(text("""
        SELECT id, sku, qty, status
        FROM inventory_reservations
        WHERE order_id = :order_id
        ORDER BY created_at ASC
    """), {"order_id": order_id}).fetchall()
    released = 0
    skipped = 0
    for row in rows or []:
        reservation_id = str(row[0] or "")
        sku = str(row[1] or "")
        qty = int(row[2] or 0)
        status = str(row[3] or "").lower()
        if not reservation_id or not sku or qty <= 0 or status != "reserved":
            skipped += 1
            continue

        claim = db.execute(
            text("UPDATE inventory_reservations SET status = 'released', "
                 "updated_at = CURRENT_TIMESTAMP WHERE id = :id AND status = 'reserved'"),
            {"id": reservation_id},
        )
        if int(getattr(claim, "rowcount", 0) or 0) <= 0:
            skipped += 1
            continue
        inventory = db.execute(text("""
            SELECT i.id
            FROM inventory i
            JOIN products p ON p.id = i.product_id
            WHERE p.sku = :sku
            ORDER BY i.updated_at DESC
            LIMIT 1
        """), {"sku": sku}).fetchone()
        if inventory:
            db.execute(
                text("UPDATE inventory SET stock = stock + :qty, updated_at = CURRENT_TIMESTAMP "
                     "WHERE id = :id"),
                {"id": str(inventory[0]), "qty": qty},
            )
        released += 1
    return {"released": released, "skipped": skipped}
