"""Supplier catalog (agnostic CORE) — the supplier + supplier_products tables the ranking reads, and a
deterministic demo seed.

inventory_agent._get_best_supplier joins `suppliers` ⋈ `supplier_products` to rank a SKU's approved
suppliers, but nothing created those tables — so the DEFAULT procurement draft path resolved no supplier
(→ NO_APPROVED_SUPPLIER). This adds the schema + an idempotent seed (suppliers, their products, and
their entries in trusted_supplier_domains — the allowlist that is the SOURCE OF TRUTH for "approved").

The approved DOMAIN lives only in trusted_supplier_domains (one source); the draft enriches the ranked
supplier with it. Vertical-blind; best-effort; idempotent.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text

_SUPPLIERS_DDL = """
CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY,
    name TEXT,
    unit_cost REAL,
    lead_time_days INTEGER,
    moq INTEGER DEFAULT 0,
    on_time_rate REAL DEFAULT 0,
    reliability_score REAL DEFAULT 0,
    recent_sla_breaches INTEGER DEFAULT 0,
    late_deliveries_30d INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_SUPPLIER_PRODUCTS_DDL = """
CREATE TABLE IF NOT EXISTS supplier_products (
    supplier_id TEXT,
    sku TEXT,
    PRIMARY KEY (supplier_id, sku)
)
"""
# matches supplier_domain_guard's table exactly (the allowlist the send-gate + draft both read)
_TRUSTED_DDL = """
CREATE TABLE IF NOT EXISTS trusted_supplier_domains (
    id TEXT PRIMARY KEY, domain TEXT NOT NULL UNIQUE, supplier_id TEXT, added_by TEXT,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP, active INTEGER DEFAULT 1, notes TEXT
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_supplier_products_sku ON supplier_products(sku)",
    "CREATE INDEX IF NOT EXISTS ix_tsd_supplier ON trusted_supplier_domains(supplier_id)",
)

# Deterministic demo suppliers — SUP-7 is the clear winner (cheaper, faster, more reliable).
_DEMO_SUPPLIERS = [
    {"id": "SUP-7", "name": "TechData Procurement", "domain": "approved-supplier.example",
     "unit_cost": 1115.0, "lead_time_days": 7, "moq": 1, "on_time_rate": 0.96, "reliability_score": 0.92},
    {"id": "SUP-3", "name": "BulkParts Co", "domain": "bulk-parts.example",
     "unit_cost": 1180.0, "lead_time_days": 12, "moq": 5, "on_time_rate": 0.85, "reliability_score": 0.80},
]
DEMO_SKUS = ["LAP-021", "GAM-1", "demo-sku"]


def ensure_tables(db) -> None:
    db.execute(text(_SUPPLIERS_DDL))
    db.execute(text(_SUPPLIER_PRODUCTS_DDL))
    db.execute(text(_TRUSTED_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


def _exists(db, sql: str, params: Dict[str, Any]) -> bool:
    try:
        return db.execute(text(sql), params).fetchone() is not None
    except Exception:
        return False


def seed_demo(db, *, skus: Optional[List[str]] = None, commit: bool = True) -> Dict[str, int]:
    """Idempotently seed the demo suppliers, their products (for ``skus``), and their trusted domains.
    Returns {suppliers, products, domains} counts inserted."""
    if db is None:
        return {}
    ensure_tables(db)
    if skus is None:  # None → demo default; an explicit [] means "register suppliers/domains only"
        skus = DEMO_SKUS
    n_sup = n_prod = n_dom = 0
    import uuid
    for s in _DEMO_SUPPLIERS:
        if not _exists(db, "SELECT 1 FROM suppliers WHERE id=:i", {"i": s["id"]}):
            db.execute(text("INSERT INTO suppliers (id, name, unit_cost, lead_time_days, moq, on_time_rate, "
                            "reliability_score, recent_sla_breaches, late_deliveries_30d, active) "
                            "VALUES (:id,:n,:c,:l,:m,:o,:r,0,0,1)"),
                       {"id": s["id"], "n": s["name"], "c": s["unit_cost"], "l": s["lead_time_days"],
                        "m": s["moq"], "o": s["on_time_rate"], "r": s["reliability_score"]})
            n_sup += 1
        if not _exists(db, "SELECT 1 FROM trusted_supplier_domains WHERE domain=:d", {"d": s["domain"]}):
            db.execute(text("INSERT INTO trusted_supplier_domains (id, domain, supplier_id, added_by, active) "
                            "VALUES (:i,:d,:s,'seed',1)"),
                       {"i": str(uuid.uuid4()), "d": s["domain"], "s": s["id"]})
            n_dom += 1
        for sku in skus:
            if not _exists(db, "SELECT 1 FROM supplier_products WHERE supplier_id=:s AND sku=:k",
                           {"s": s["id"], "k": sku}):
                db.execute(text("INSERT INTO supplier_products (supplier_id, sku) VALUES (:s,:k)"),
                           {"s": s["id"], "k": sku})
                n_prod += 1
    if commit:
        try:
            db.commit()
        except Exception:
            return {"suppliers": n_sup, "products": n_prod, "domains": n_dom}
    return {"suppliers": n_sup, "products": n_prod, "domains": n_dom}


def all_catalog_skus(db) -> List[str]:
    """Every ACTIVE catalog SKU — the set the recommender can surface. Supplier coverage tracks this so
    whatever SKU is recommended resolves an approved supplier (instead of a hardcoded shortlist that the
    recommender's real SKUs fall outside of → NO_APPROVED_SUPPLIER). Best-effort; [] if no products table."""
    if db is None:
        return []
    try:
        rows = db.execute(text(
            "SELECT sku FROM products WHERE COALESCE(active,1)=1 AND sku IS NOT NULL AND sku <> ''"
        )).fetchall()
        return sorted({str(r[0]) for r in rows if r and r[0]})
    except Exception:
        return []


def ensure_supplier_coverage(db, *, commit: bool = True) -> Dict[str, int]:
    """Idempotently ensure every active catalog SKU (plus the demo SKUs the e2e fixtures use) has at least
    one approved supplier — coverage follows the catalog, so the procurement draft path no longer dead-ends
    at NO_APPROVED_SUPPLIER for a SKU the recommender actually chose. Self-healing: adds only the missing
    supplier_products rows. Returns {suppliers, products, domains} counts inserted."""
    skus = sorted(set(DEMO_SKUS) | set(all_catalog_skus(db)))
    return seed_demo(db, skus=skus, commit=commit)


def domain_for_supplier(db, supplier_id: str) -> Optional[str]:
    """The approved domain for a supplier, from the allowlist (the source of truth). None if not approved."""
    if db is None or not supplier_id:
        return None
    try:
        row = db.execute(text("SELECT domain FROM trusted_supplier_domains WHERE supplier_id=:s "
                              "AND COALESCE(active,1)=1 LIMIT 1"), {"s": str(supplier_id)}).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def cheapest_wholesale_cents(db, sku: str) -> Optional[int]:
    """The lowest active-supplier wholesale for a sku, in CENTS — the economics fallback when there is
    no live validated quote (suppliers.unit_cost is stored in dollars). None if no supplier carries it."""
    if db is None or not sku:
        return None
    try:
        row = db.execute(text(
            "SELECT MIN(s.unit_cost) FROM suppliers s JOIN supplier_products sp ON sp.supplier_id = s.id "
            "WHERE sp.sku = :k AND COALESCE(s.active,1)=1 AND s.unit_cost IS NOT NULL"),
            {"k": str(sku)}).fetchone()
        if not row or row[0] is None:
            return None
        return int(round(float(row[0]) * 100))
    except Exception:
        return None


# Verified vendor contacts for the demo suppliers — so a draft resolves a CONTACT EMAIL (not just the
# domain) via Supplier_Inbox_Reader → kyv_vendors.contact_email. Each must be on its own approved domain.
_DEMO_VENDOR_CONTACTS = [
    ("TechData Procurement", "approved-supplier.example", "orders@approved-supplier.example"),
    ("BulkParts Co", "bulk-parts.example", "sales@bulk-parts.example"),
]


def _register_vendor_if_absent(lookup, register, *, tenant_id, name, domain, email) -> bool:
    try:
        if lookup(tenant_id=tenant_id, domain=domain):
            return False
        res = register(tenant_id=tenant_id, legal_name=name, verified_domain=domain,
                       contact_email=email, risk_tier="low") or {}
        return bool(res.get("ok", True))
    except Exception:
        return False  # best-effort seed — observable return, never a silent swallow


def seed_demo_vendor_contacts(*, tenant_id: str = "default") -> int:
    """Register the demo suppliers as KYV vendors with a verified contact email (idempotent). Returns the
    count newly registered. After this, the draft's recipient_email resolves to the contact email instead
    of the bare domain (the live-packet polish fix)."""
    try:
        from src.app.security.kyv_registry import lookup_vendor_by_domain, register_vendor
    except Exception:
        return 0
    return sum(1 for name, domain, email in _DEMO_VENDOR_CONTACTS
               if _register_vendor_if_absent(lookup_vendor_by_domain, register_vendor,
                                             tenant_id=tenant_id, name=name, domain=domain, email=email))


# A short prior-dealings history per demo supplier domain, as (days_ago, invoice_amount_dollars). The
# draft's evidence packet reads this (Supplier_Inbox_Reader) to show "N prior dealings, last invoice $X" —
# the "how we usually deal with them" context the operator sees before approving a send.
_DEMO_SUPPLIER_HISTORY = [
    ("approved-supplier.example", [(58, 6690.0), (33, 5575.0), (9, 7805.0)]),
    ("bulk-parts.example", [(47, 5900.0), (15, 7080.0)]),
]


def _seed_history_if_absent(record, recent_ctx, *, tenant_id, domain, events, now) -> int:
    try:
        ctx = recent_ctx(domain=domain, tenant_id=tenant_id)
        if ctx and ctx.observations:
            return 0  # already seeded — never duplicate history rows
        from datetime import timedelta
        n = 0
        for days_ago, amount in events:
            record(tenant_id=tenant_id, sender_domain=domain,
                   event_datetime=(now - timedelta(days=days_ago)).isoformat(),
                   invoice_amount=amount, attachment_count=1)
            n += 1
        return n
    except Exception:
        return 0  # best-effort seed — observable return, never a silent swallow


def seed_demo_supplier_history(*, tenant_id: str = "default") -> int:
    """Seed a few historical supplier email events (send-time + invoice amount) for the demo supplier
    domains, so the draft's evidence packet shows real prior-dealings context ("N observations, last
    invoice $X") instead of an empty history. Idempotent: a domain that already has events is skipped.
    Returns the count of events inserted."""
    try:
        from datetime import datetime, timezone
        from src.app.security.supplier_baseline import record_email_event
        from src.app.services.supplier_inbox_reader import recent_supplier_context
    except Exception:
        return 0
    now = datetime.now(timezone.utc)
    return sum(_seed_history_if_absent(record_email_event, recent_supplier_context,
                                       tenant_id=tenant_id, domain=domain, events=events, now=now)
               for domain, events in _DEMO_SUPPLIER_HISTORY)
