"""Canonical catalog identity + integration mapping (agnostic CORE).

Three tables that complete the canonical model alongside commerce_catalog (price/stock):
  • product       — catalog identity (title/brand/category/gtin) + vertical attributes in a JSON column
                    (the "flavour in data" rule, as schema). One row per sellable concept.
  • variant       — the sellable SKU under a product (sku/gtin + its own attributes).
  • external_ref  — the INTEGRATION SEAM: one row per (canonical entity ↔ platform external id), with
                    the raw payload retained for audit/debug. Adapters write here; core never references
                    a platform id directly, so a second platform (Magento/Woo) needs no core change.

Vertical attributes live in attributes_json (JSON text on sqlite / JSONB on Postgres) — never new
columns per vertical, enforced by the no-flavour ratchet. Idempotent upsert on the natural key;
best-effort, never raises.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

# DDL kept textually identical to alembic/versions/20260626_catalog_entities.py (drift test enforces it).
_PRODUCT_DDL = """
CREATE TABLE IF NOT EXISTS product (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    title TEXT,
    brand TEXT,
    category TEXT,
    gtin TEXT,
    attributes_json TEXT,
    status TEXT DEFAULT 'active',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_VARIANT_DDL = """
CREATE TABLE IF NOT EXISTS variant (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    product_id TEXT,
    sku TEXT,
    gtin TEXT,
    attributes_json TEXT,
    status TEXT DEFAULT 'active',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_EXTERNAL_REF_DDL = """
CREATE TABLE IF NOT EXISTS external_ref (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    entity_type TEXT,
    entity_id TEXT,
    platform TEXT,
    external_id TEXT,
    raw_json TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_variant_sku ON variant(tenant_id, sku)",
    "CREATE INDEX IF NOT EXISTS ix_variant_product ON variant(product_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_extref_key ON external_ref(tenant_id, platform, entity_type, external_id)",
)


def ensure_tables(db) -> None:
    db.execute(text(_PRODUCT_DDL))
    db.execute(text(_VARIANT_DDL))
    db.execute(text(_EXTERNAL_REF_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


# ── product / variant ────────────────────────────────────────────────────────
def upsert_product(db, *, product_id: str, title: str = "", brand: str = "", category: str = "",
                   gtin: str = "", attributes: Optional[Dict[str, Any]] = None, status: str = "active",
                   tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> bool:
    if db is None or not product_id:
        return False
    try:
        ensure_tables(db)
        p = {"t": str(tenant_id).strip() or DEFAULT_TENANT, "id": str(product_id), "ti": title,
             "br": brand, "ca": category, "g": gtin, "a": json.dumps(attributes or {}, default=str), "st": status}
        res = db.execute(text(
            "UPDATE product SET title=:ti, brand=:br, category=:ca, gtin=:g, attributes_json=:a, "
            "status=:st, updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:t AND id=:id"), p)
        if not (getattr(res, "rowcount", 0) or 0):
            db.execute(text(
                "INSERT INTO product (id, tenant_id, title, brand, category, gtin, attributes_json, status) "
                "VALUES (:id,:t,:ti,:br,:ca,:g,:a,:st)"), p)
        if commit:
            db.commit()
        return True
    except Exception:
        return False


def upsert_variant(db, *, sku: str, product_id: str = "", gtin: str = "",
                   attributes: Optional[Dict[str, Any]] = None, status: str = "active",
                   tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> bool:
    """Upsert a variant keyed on (tenant, sku) — the sku is the stable sellable id."""
    if db is None or not sku:
        return False
    try:
        ensure_tables(db)
        v = {"t": str(tenant_id).strip() or DEFAULT_TENANT, "k": str(sku), "pid": product_id, "g": gtin,
             "a": json.dumps(attributes or {}, default=str), "st": status}
        res = db.execute(text(
            "UPDATE variant SET product_id=:pid, gtin=:g, attributes_json=:a, status=:st, "
            "updated_at=CURRENT_TIMESTAMP WHERE tenant_id=:t AND sku=:k"), v)
        if not (getattr(res, "rowcount", 0) or 0):
            db.execute(text(
                "INSERT INTO variant (id, tenant_id, product_id, sku, gtin, attributes_json, status) "
                "VALUES (:id,:t,:pid,:k,:g,:a,:st)"), {**v, "id": str(uuid.uuid4())})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


def variant_by_sku(db, sku: str, *, tenant_id: str = DEFAULT_TENANT) -> Optional[Dict[str, Any]]:
    if db is None or not sku:
        return None
    try:
        ensure_tables(db)
        row = db.execute(text(
            "SELECT product_id, sku, gtin, attributes_json, status FROM variant "
            "WHERE tenant_id=:t AND sku=:k LIMIT 1"),
            {"t": str(tenant_id).strip() or DEFAULT_TENANT, "k": str(sku)}).fetchone()
        if not row:
            return None
        try:
            attrs = json.loads(row[3]) if row[3] else {}
        except Exception:
            attrs = {}
        return {"product_id": row[0], "sku": row[1], "gtin": row[2],
                "attributes": attrs if isinstance(attrs, dict) else {}, "status": row[4]}
    except Exception:
        return None


# ── external_ref (the integration seam) ──────────────────────────────────────
def upsert_external_ref(db, *, platform: str, entity_type: str, external_id: str, entity_id: str,
                        raw: Optional[Dict[str, Any]] = None, tenant_id: str = DEFAULT_TENANT,
                        commit: bool = False) -> bool:
    """Map a platform's id ↔ our canonical id. Idempotent on (tenant, platform, entity_type, external_id)."""
    if db is None or not platform or not external_id:
        return False
    try:
        ensure_tables(db)
        r = {"t": str(tenant_id).strip() or DEFAULT_TENANT, "pl": str(platform), "et": str(entity_type),
             "ex": str(external_id), "en": str(entity_id), "raw": json.dumps(raw or {}, default=str)}
        res = db.execute(text(
            "UPDATE external_ref SET entity_id=:en, raw_json=:raw, updated_at=CURRENT_TIMESTAMP "
            "WHERE tenant_id=:t AND platform=:pl AND entity_type=:et AND external_id=:ex"), r)
        if not (getattr(res, "rowcount", 0) or 0):
            db.execute(text(
                "INSERT INTO external_ref (id, tenant_id, entity_type, entity_id, platform, external_id, "
                "raw_json) VALUES (:id,:t,:et,:en,:pl,:ex,:raw)"), {**r, "id": str(uuid.uuid4())})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


def resolve_external(db, *, platform: str, entity_type: str, external_id: str,
                     tenant_id: str = DEFAULT_TENANT) -> Optional[str]:
    """The canonical entity_id for a platform's external id, or None."""
    if db is None or not platform or not external_id:
        return None
    try:
        ensure_tables(db)
        row = db.execute(text(
            "SELECT entity_id FROM external_ref WHERE tenant_id=:t AND platform=:pl AND entity_type=:et "
            "AND external_id=:ex LIMIT 1"),
            {"t": str(tenant_id).strip() or DEFAULT_TENANT, "pl": str(platform), "et": str(entity_type),
             "ex": str(external_id)}).fetchone()
        return row[0] if row else None
    except Exception:
        return None
