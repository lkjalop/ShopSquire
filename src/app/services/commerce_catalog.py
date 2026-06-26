"""Canonical commerce catalog (agnostic CORE) — retail price + on-hand inventory, the two tables the
deal-economics JOIN reads and that platform adapters (Shopify/Magento/…) write into.

Separates the things that change independently:
  • price_book_entry  — our RETAIL price per (sku, channel, currency). Price ≠ product: it's channel-
                        and currency-specific and changes often, so it lives apart from any catalog row.
  • inventory_level   — stock per (sku, location). on_hand / reserved / available — the only honest way
                        to avoid overselling (available = on_hand − reserved).

Both are upserted idempotently on their natural key, so an adapter re-syncing the same feed converges
instead of duplicating. Vertical-blind (sku is an opaque id; cents + counts only) and best-effort —
never raises into a caller. The canonical store is RELATIONAL on purpose (money + stock need a
transactional system of record); vertical attributes belong in JSON columns on the catalog, not here.

Flag-gated consumption: economics reads these only when COMMERCE_CATALOG_ENABLED is set, so default
behaviour (retail derived from the buyer's selected option) is unchanged until the catalog is populated.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

# DDL kept textually identical to alembic/versions/20260626_commerce_catalog.py (drift test enforces it).
_PRICE_BOOK_DDL = """
CREATE TABLE IF NOT EXISTS price_book_entry (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    sku TEXT NOT NULL,
    channel TEXT DEFAULT 'default',
    currency TEXT DEFAULT 'AUD',
    list_cents INTEGER,
    sale_cents INTEGER,
    valid_from TEXT,
    valid_to TEXT,
    source TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INVENTORY_DDL = """
CREATE TABLE IF NOT EXISTS inventory_level (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    sku TEXT NOT NULL,
    location_id TEXT DEFAULT 'default',
    on_hand INTEGER DEFAULT 0,
    reserved INTEGER DEFAULT 0,
    available INTEGER,
    source TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_pbe_key ON price_book_entry(tenant_id, sku, channel, currency)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_inv_key ON inventory_level(tenant_id, sku, location_id)",
)

DEFAULT_TENANT = "default"


def catalog_enabled() -> bool:
    return str(os.getenv("COMMERCE_CATALOG_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def ensure_tables(db) -> None:
    db.execute(text(_PRICE_BOOK_DDL))
    db.execute(text(_INVENTORY_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


# ── writes (idempotent upsert on the natural key) ────────────────────────────
def upsert_price(db, *, sku: str, list_cents: Any, sale_cents: Any = None, channel: str = "default",
                 currency: str = "AUD", source: str = "", valid_from: Optional[str] = None,
                 valid_to: Optional[str] = None, tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> bool:
    """Set the retail price for (tenant, sku, channel, currency). Returns True on a new/updated row."""
    if db is None or not sku:
        return False
    try:
        ensure_tables(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        params = {"t": tid, "k": str(sku), "ch": channel, "cur": currency,
                  "l": _int(list_cents), "s": _int(sale_cents), "vf": valid_from, "vt": valid_to,
                  "src": source or ""}
        res = db.execute(text(
            "UPDATE price_book_entry SET list_cents=:l, sale_cents=:s, valid_from=:vf, valid_to=:vt, "
            "source=:src, updated_at=CURRENT_TIMESTAMP "
            "WHERE tenant_id=:t AND sku=:k AND channel=:ch AND currency=:cur"), params)
        if not (getattr(res, "rowcount", 0) or 0):
            db.execute(text(
                "INSERT INTO price_book_entry (id, tenant_id, sku, channel, currency, list_cents, "
                "sale_cents, valid_from, valid_to, source) "
                "VALUES (:id,:t,:k,:ch,:cur,:l,:s,:vf,:vt,:src)"), {**params, "id": str(uuid.uuid4())})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


def upsert_inventory(db, *, sku: str, on_hand: Any, reserved: Any = 0, location_id: str = "default",
                     source: str = "", tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> bool:
    """Set stock for (tenant, sku, location). available is derived = max(0, on_hand − reserved)."""
    if db is None or not sku:
        return False
    try:
        ensure_tables(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        oh = _int(on_hand) or 0
        rv = _int(reserved) or 0
        avail = max(0, oh - rv)
        params = {"t": tid, "k": str(sku), "loc": location_id, "oh": oh, "rv": rv, "av": avail,
                  "src": source or ""}
        res = db.execute(text(
            "UPDATE inventory_level SET on_hand=:oh, reserved=:rv, available=:av, source=:src, "
            "updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:t AND sku=:k AND location_id=:loc"), params)
        if not (getattr(res, "rowcount", 0) or 0):
            db.execute(text(
                "INSERT INTO inventory_level (id, tenant_id, sku, location_id, on_hand, reserved, "
                "available, source) VALUES (:id,:t,:k,:loc,:oh,:rv,:av,:src)"),
                {**params, "id": str(uuid.uuid4())})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


# ── reads (the economics JOIN + availability) ────────────────────────────────
def retail_unit_cents(db, sku: str, *, channel: str = "default", currency: str = "AUD",
                      tenant_id: str = DEFAULT_TENANT) -> Optional[int]:
    """Our per-unit retail for a sku — sale price if set, else list. None when not priced."""
    if db is None or not sku:
        return None
    try:
        ensure_tables(db)
        row = db.execute(text(
            "SELECT sale_cents, list_cents FROM price_book_entry "
            "WHERE tenant_id=:t AND sku=:k AND channel=:ch AND currency=:cur "
            "ORDER BY updated_at DESC LIMIT 1"),
            {"t": str(tenant_id).strip() or DEFAULT_TENANT, "k": str(sku), "ch": channel, "cur": currency}
        ).fetchone()
        if not row:
            return None
        return _int(row[0]) if row[0] is not None else _int(row[1])
    except Exception:
        return None


def inventory_for(db, sku: str, *, location_id: Optional[str] = None,
                  tenant_id: str = DEFAULT_TENANT) -> Optional[Dict[str, int]]:
    """Stock for a sku, summed across locations (or one location). None when the sku has no rows."""
    if db is None or not sku:
        return None
    try:
        ensure_tables(db)
        sql = ("SELECT COALESCE(SUM(on_hand),0), COALESCE(SUM(reserved),0), COALESCE(SUM(available),0) "
               "FROM inventory_level WHERE tenant_id=:t AND sku=:k")
        params: Dict[str, Any] = {"t": str(tenant_id).strip() or DEFAULT_TENANT, "k": str(sku)}
        if location_id is not None:
            sql += " AND location_id=:loc"
            params["loc"] = location_id
        cnt = db.execute(text("SELECT COUNT(*) FROM inventory_level WHERE tenant_id=:t AND sku=:k"
                              + (" AND location_id=:loc" if location_id is not None else "")), params).scalar()
        if not cnt:
            return None
        row = db.execute(text(sql), params).fetchone()
        return {"on_hand": int(row[0]), "reserved": int(row[1]), "available": int(row[2])}
    except Exception:
        return None


# ── deterministic demo seed (so the economics JOIN has data) ─────────────────
_DEMO_PRICES = [("LAP-021", 120000), ("GAM-1", 209900), ("demo-sku", 120000)]   # retail cents
_DEMO_STOCK = [("LAP-021", 4), ("GAM-1", 6), ("demo-sku", 4)]                    # on_hand


def seed_demo(db, *, tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> Dict[str, int]:
    """Idempotently seed retail prices + stock for the demo SKUs. Returns {prices, inventory} counts."""
    if db is None:
        return {}
    ensure_tables(db)
    n_p = sum(1 for sku, cents in _DEMO_PRICES
              if upsert_price(db, sku=sku, list_cents=cents, channel="default", currency="AUD",
                              source="seed", tenant_id=tenant_id))
    n_i = sum(1 for sku, oh in _DEMO_STOCK
              if upsert_inventory(db, sku=sku, on_hand=oh, source="seed", tenant_id=tenant_id))
    if commit:
        try:
            db.commit()
        except Exception:
            return {"prices": n_p, "inventory": n_i}
    return {"prices": n_p, "inventory": n_i}


def _int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None
