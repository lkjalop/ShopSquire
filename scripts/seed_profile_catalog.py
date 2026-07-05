"""Generic, profile-driven catalog seeder (vertical-BLIND mechanism).

The per-vertical demo used the profile's ``demo_fallback_catalog`` ONLY on the zero-result fallback
path — so a fashion/pharmacy switch never exercised real retrieval, ranking, stock, or the fast
path. This seeds those SAME profile rows into the real ``products`` + ``inventory`` tables, so a
switched vertical runs the identical DB-backed pipeline electronics does.

Vertical-blind: the seeder reads whatever ``demo_fallback_catalog`` the named profile carries and
inserts it verbatim. Zero product vocabulary here — the vocabulary lives in the profile JSON.
Idempotent + self-healing (per-SKU existence check; missing inventory row is added on re-run),
portable text() (SQLite + Postgres). Returns the count of NEW products inserted.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text


def _profile_catalog(profile_id: str) -> List[Dict[str, Any]]:
    """Read a NAMED profile's demo_fallback_catalog (profile_slot takes an explicit profile_id, so
    this does not depend on the request-scoped active profile — safe at startup / CLI)."""
    from src.app.platform.store_profile import profile_slot
    rows = profile_slot("demo_fallback_catalog", profile_id=profile_id, default=[]) or []
    return [r for r in rows if isinstance(r, dict) and r.get("sku")]


def seed_profile_catalog(db, profile_id: str, *, default_stock: int = 24) -> int:
    """Insert a profile's demo catalog into products+inventory. Idempotent per SKU. Returns NEW count."""
    inserted = 0
    for i, row in enumerate(_profile_catalog(profile_id)):
        sku = str(row["sku"])
        existing = db.execute(text("SELECT id FROM products WHERE sku = :sku"), {"sku": sku}).fetchone()
        if existing:
            pid = existing[0]
        else:
            pid = str(uuid.uuid4())
            price_cents = int(row.get("price_cents") or (int(row.get("price") or 0) * 100))
            db.execute(
                text("INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at) "
                     "VALUES (:id, :sku, :name, :price_cents, :currency, :specs, 1, :updated_at)"),
                {"id": pid, "sku": sku, "name": str(row.get("name") or sku),
                 "price_cents": price_cents, "currency": str(row.get("currency") or "USD"),
                 "specs": json.dumps(row.get("specs") or {}), "updated_at": datetime.utcnow()},
            )
            inserted += 1
        has_inv = db.execute(text("SELECT 1 FROM inventory WHERE product_id = :pid LIMIT 1"),
                             {"pid": pid}).fetchone()
        if not has_inv:
            stock = int(row.get("stock") if row.get("stock") is not None else default_stock)
            db.execute(
                text("INSERT INTO inventory (id, product_id, stock, warehouse, updated_at) "
                     "VALUES (:id, :pid, :stock, 'default', :updated_at)"),
                {"id": str(uuid.uuid4()), "pid": pid, "stock": stock, "updated_at": datetime.utcnow()},
            )
    return inserted


def main(profile_id: Optional[str] = None) -> None:
    import sys
    from src.app.models.db import db_session
    pid = profile_id or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not pid:
        print("usage: python -m scripts.seed_profile_catalog <profile_id>  (e.g. fashion, pharmacy)")
        return
    with db_session() as db:
        n = seed_profile_catalog(db, pid)
        db.commit()
    print(f"seeded profile '{pid}': {n} new products")


if __name__ == "__main__":
    main()
