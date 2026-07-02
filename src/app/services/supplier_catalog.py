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

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.supplier_catalog")

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
# Per-(supplier, SKU) commercial terms — richer than the supplier-level defaults. All optional/additive
# (migrated in idempotently) and vertical-blind (cents / days / qty / opaque region & contract strings).
_SUPPLIER_PRODUCTS_COLUMNS = (
    ("moq", "INTEGER"),                    # minimum order quantity for THIS sku from THIS supplier
    ("min_order_value_cents", "INTEGER"),  # minimum order VALUE (some suppliers gate on $ not qty)
    ("lead_time_days", "INTEGER"),         # per-sku dispatch lead time
    ("region", "TEXT"),                    # warehouse / serviceable region (faster/cheaper when local)
    ("on_time_rate", "REAL"),              # per-sku reliability
    ("price_breaks", "TEXT"),              # JSON: [{"min_qty": N, "discount_pct": P}] — volume tiers
    ("contract_status", "TEXT"),           # 'preferred' | 'spot' | 'contracted' (opaque)
    ("active", "INTEGER"),
)
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
     "unit_cost": 1115.0, "lead_time_days": 7, "moq": 1, "on_time_rate": 0.96, "reliability_score": 0.92,
     # per-SKU commercial terms (the demo seed populates supplier_products with these)
     "terms": {"moq": 1, "min_order_value_cents": 0, "lead_time_days": 7, "region": "AU-metro",
               "on_time_rate": 0.96, "contract_status": "preferred",
               "price_breaks": [{"min_qty": 25, "discount_pct": 5}, {"min_qty": 50, "discount_pct": 10}]}},
    {"id": "SUP-3", "name": "BulkParts Co", "domain": "bulk-parts.example",
     "unit_cost": 1180.0, "lead_time_days": 12, "moq": 5, "on_time_rate": 0.85, "reliability_score": 0.80,
     "terms": {"moq": 5, "min_order_value_cents": 500000, "lead_time_days": 12, "region": "AU",
               "on_time_rate": 0.85, "contract_status": "spot",
               "price_breaks": [{"min_qty": 20, "discount_pct": 8}, {"min_qty": 50, "discount_pct": 15}]}},
]
DEMO_SKUS = ["LAP-021", "GAM-1", "GAM-0002", "demo-sku"]

# Routed demo suppliers: these make procurement demos behave like a real multi-supplier catalog instead
# of every SKU collapsing to the same generic supplier. ``seed_demo`` above is intentionally kept as the
# small legacy fixture used by older tests; ``ensure_supplier_coverage`` uses these category/SKU routes.
# DESIGN NOTE (why these RECORDS live in core but the ROUTING RULES do not): the product->supplier
# vocabulary (brand/model/GPU tokens -> a supplier id) is electronics FLAVOUR and lives in the
# StoreProfile (supplier_routing_rules) so core stays vertical-blind. These records are opaque demo DATA
# (company names + .example domains -- not product vocabulary, so ratchet-clean) and feed the LIVE
# self-healing ``ensure_supplier_coverage`` path that runs outside the seed script; keeping them here
# keeps that path self-contained. Swap the vertical -> swap the profile's routing rules; records stay generic.
_ROUTED_DEMO_SUPPLIERS = [
    {"id": "SUP-BIZ", "name": "Northbridge Business Systems", "domain": "northbridge-business.example",
     "unit_cost": 1095.0, "lead_time_days": 6, "moq": 5, "on_time_rate": 0.95, "reliability_score": 0.91,
     "terms": {"moq": 5, "min_order_value_cents": 300000, "lead_time_days": 6, "region": "AU-metro",
               "on_time_rate": 0.95, "contract_status": "contracted",
               "price_breaks": [{"min_qty": 20, "discount_pct": 4}, {"min_qty": 50, "discount_pct": 9}]}},
    {"id": "SUP-CREATOR", "name": "CreatorFleet Wholesale", "domain": "creatorfleet.example",
     "unit_cost": 1260.0, "lead_time_days": 7, "moq": 10, "on_time_rate": 0.93, "reliability_score": 0.90,
     "terms": {"moq": 10, "min_order_value_cents": 700000, "lead_time_days": 7, "region": "AU",
               "on_time_rate": 0.93, "contract_status": "preferred",
               "price_breaks": [{"min_qty": 25, "discount_pct": 5}, {"min_qty": 50, "discount_pct": 11}]}},
    {"id": "SUP-APPLE", "name": "Orchard Device Supply", "domain": "orchard-device.example",
     "unit_cost": 1490.0, "lead_time_days": 9, "moq": 3, "on_time_rate": 0.91, "reliability_score": 0.88,
     "terms": {"moq": 3, "min_order_value_cents": 500000, "lead_time_days": 9, "region": "AU-metro",
               "on_time_rate": 0.91, "contract_status": "approved",
               "price_breaks": [{"min_qty": 10, "discount_pct": 3}, {"min_qty": 25, "discount_pct": 6}]}},
    {"id": "SUP-PERIPH", "name": "PeriLink Accessories", "domain": "perilink-accessories.example",
     "unit_cost": 55.0, "lead_time_days": 4, "moq": 20, "on_time_rate": 0.97, "reliability_score": 0.93,
     "terms": {"moq": 20, "min_order_value_cents": 100000, "lead_time_days": 4, "region": "AU-metro",
               "on_time_rate": 0.97, "contract_status": "preferred",
               "price_breaks": [{"min_qty": 50, "discount_pct": 8}, {"min_qty": 100, "discount_pct": 14}]}},
    {"id": "SUP-OFFICE", "name": "Harbour Office Wholesale", "domain": "harbour-office.example",
     "unit_cost": 180.0, "lead_time_days": 5, "moq": 5, "on_time_rate": 0.94, "reliability_score": 0.89,
     "terms": {"moq": 5, "min_order_value_cents": 150000, "lead_time_days": 5, "region": "AU",
               "on_time_rate": 0.94, "contract_status": "contracted",
               "price_breaks": [{"min_qty": 20, "discount_pct": 6}, {"min_qty": 75, "discount_pct": 12}]}},
]
_ALL_DEMO_SUPPLIER_IDS = {s["id"] for s in (_DEMO_SUPPLIERS + _ROUTED_DEMO_SUPPLIERS)}


# Preferred COMMUNICATION channel per demo supplier — how each supplier accepts an order/RFQ. Varied on
# purpose so the demo shows the router route different suppliers differently (agent-drafts an email vs a
# human-only phone/portal task vs a system-to-system EDI/cXML/API handoff). Opaque DATA, vertical-blind.
_DEMO_SUPPLIER_CHANNELS = {
    "SUP-7": "edi",           # a large distributor → EDI (X12 850) integration
    "SUP-3": "email",
    "SUP-BIZ": "email",       # the standard demoable draft path
    "SUP-CREATOR": "api",     # modern supplier with a REST API
    "SUP-APPLE": "portal",    # submit via the supplier's web portal (human logs in)
    "SUP-PERIPH": "phone",    # small accessory supplier → a HUMAN calls (never an LLM voice call)
    "SUP-OFFICE": "cxml",     # Ariba/Coupa network (cXML)
}


def _ensure_suppliers_columns(db) -> None:
    """Idempotently add suppliers.preferred_channel (additive ALTER, sqlite + pg). Best-effort."""
    try:
        existing = {str(r[1]) for r in db.execute(text("PRAGMA table_info(suppliers)")).fetchall()}
    except Exception:
        try:
            existing = {str(r[0]) for r in db.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='suppliers'")).fetchall()}
        except Exception:
            return
    if "preferred_channel" not in existing:
        try:
            db.execute(text("ALTER TABLE suppliers ADD COLUMN preferred_channel TEXT"))
        except Exception as exc:
            logger.debug("suppliers.preferred_channel add skipped: %s", exc)


def apply_demo_supplier_channels(db) -> int:
    """Stamp the demo suppliers' preferred_channel (idempotent). Returns rows updated. Lets the live
    self-healing coverage path assign channels to already-seeded suppliers without a re-seed."""
    _ensure_suppliers_columns(db)
    n = 0
    for sid, ch in _DEMO_SUPPLIER_CHANNELS.items():
        try:
            res = db.execute(text("UPDATE suppliers SET preferred_channel = :c WHERE id = :i "
                                  "AND (preferred_channel IS NULL OR preferred_channel = '')"),
                             {"c": ch, "i": sid})
            n += int(getattr(res, "rowcount", 0) or 0)
        except Exception as exc:
            logger.debug("supplier channel stamp skipped for %s: %s", sid, exc)
    return n


def ensure_tables(db) -> None:
    db.execute(text(_SUPPLIERS_DDL))
    db.execute(text(_SUPPLIER_PRODUCTS_DDL))
    db.execute(text(_TRUSTED_DDL))
    _ensure_supplier_products_columns(db)
    _ensure_suppliers_columns(db)
    for idx in _INDEXES:
        db.execute(text(idx))


def _ensure_supplier_products_columns(db) -> None:
    """Idempotently add the per-SKU commercial-terms columns (ALTER ADD COLUMN is additive in SQLite +
    Postgres; we add only the ones missing). Best-effort — a failed add never breaks the read path."""
    try:
        existing = {str(r[1]) for r in db.execute(text("PRAGMA table_info(supplier_products)")).fetchall()}
    except Exception:
        # Non-SQLite (e.g. Postgres) — try information_schema; on any failure, skip (columns may already exist)
        try:
            existing = {str(r[0]) for r in db.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='supplier_products'"
            )).fetchall()}
        except Exception:
            return
    for col, typ in _SUPPLIER_PRODUCTS_COLUMNS:
        if col not in existing:
            try:
                db.execute(text(f"ALTER TABLE supplier_products ADD COLUMN {col} {typ}"))
            except Exception as exc:
                logger.debug("supplier_products ADD COLUMN %s skipped: %s", col, exc)


def supplier_terms(db, supplier_id: str, sku: str, *, tenant_id: str = "default") -> Dict[str, Any]:
    """Merged commercial terms for (supplier, sku): per-SKU values (supplier_products) override the
    supplier-level defaults (suppliers). Returns {moq, min_order_value_cents, lead_time_days, region,
    on_time_rate, price_breaks: [...], contract_status}. Empty dict on any failure. Vertical-blind."""
    import json as _json
    out: Dict[str, Any] = {}
    try:
        srow = db.execute(text("SELECT moq, lead_time_days, on_time_rate FROM suppliers WHERE id=:i LIMIT 1"),
                          {"i": str(supplier_id)}).fetchone()
        if srow:
            out["moq"] = int(srow[0]) if srow[0] is not None else None
            out["lead_time_days"] = int(srow[1]) if srow[1] is not None else None
            out["on_time_rate"] = float(srow[2]) if srow[2] is not None else None
    except Exception:
        # resilient to a minimal suppliers table (e.g. only id/name/moq) — moq is the key default
        try:
            srow = db.execute(text("SELECT moq FROM suppliers WHERE id=:i LIMIT 1"),
                              {"i": str(supplier_id)}).fetchone()
            if srow and srow[0] is not None:
                out["moq"] = int(srow[0])
        except Exception as exc:
            logger.debug("supplier_terms suppliers lookup failed for %s: %s", supplier_id, exc)
    try:
        prow = db.execute(text(
            "SELECT moq, min_order_value_cents, lead_time_days, region, on_time_rate, price_breaks, "
            "contract_status FROM supplier_products WHERE supplier_id=:s AND sku=:k LIMIT 1"),
            {"s": str(supplier_id), "k": str(sku)}).fetchone()
    except Exception:
        prow = None
    if prow:
        for i, key in enumerate(("moq", "min_order_value_cents", "lead_time_days", "region",
                                 "on_time_rate", "price_breaks", "contract_status")):
            v = prow[i]
            if v is None:
                continue
            if key == "price_breaks":
                try:
                    out["price_breaks"] = _json.loads(v) if isinstance(v, str) else (v or [])
                except Exception:
                    out["price_breaks"] = []
            elif key in ("moq", "min_order_value_cents", "lead_time_days"):
                out[key] = int(v)
            elif key == "on_time_rate":
                out[key] = float(v)
            else:
                out[key] = v
    out.setdefault("price_breaks", [])
    return out


def price_break_advisory(quantity: int, terms: Dict[str, Any]) -> Optional[str]:
    """The next volume tier ABOVE the ordered quantity, if any — the "order a bit more, pay less" nudge.
    Returns a buyer/operator-facing line or None. Pure; vertical-blind."""
    try:
        q = int(quantity or 0)
        breaks = sorted(
            [{"min_qty": int(b.get("min_qty")), "discount_pct": float(b.get("discount_pct"))}
             for b in (terms or {}).get("price_breaks", []) if isinstance(b, dict) and b.get("min_qty")],
            key=lambda b: b["min_qty"])
    except Exception:
        return None
    nxt = next((b for b in breaks if b["min_qty"] > q), None)
    if not nxt:
        return None
    return (f"Volume tier: ordering {nxt['min_qty']}+ units unlocks ~{nxt['discount_pct']:.0f}% off "
            f"(you're ordering {q}).")


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
        _t = s.get("terms") or {}
        import json as _json
        _params = {"s": s["id"], "moq": _t.get("moq"), "mov": _t.get("min_order_value_cents"),
                   "lt": _t.get("lead_time_days"), "rg": _t.get("region"), "ot": _t.get("on_time_rate"),
                   "pb": _json.dumps(_t.get("price_breaks") or []), "cs": _t.get("contract_status")}
        for sku in skus:
            if not _exists(db, "SELECT 1 FROM supplier_products WHERE supplier_id=:s AND sku=:k",
                           {"s": s["id"], "k": sku}):
                db.execute(text(
                    "INSERT INTO supplier_products (supplier_id, sku, moq, min_order_value_cents, "
                    "lead_time_days, region, on_time_rate, price_breaks, contract_status, active) "
                    "VALUES (:s,:k,:moq,:mov,:lt,:rg,:ot,:pb,:cs,1)"), {**_params, "k": sku})
                n_prod += 1
            else:
                # backfill commercial terms onto a pre-migration row (null terms) — COALESCE keeps any
                # value already set, fills the gaps; idempotent so re-seeding is safe.
                db.execute(text(
                    "UPDATE supplier_products SET moq=COALESCE(moq,:moq), "
                    "min_order_value_cents=COALESCE(min_order_value_cents,:mov), "
                    "lead_time_days=COALESCE(lead_time_days,:lt), region=COALESCE(region,:rg), "
                    "on_time_rate=COALESCE(on_time_rate,:ot), contract_status=COALESCE(contract_status,:cs), "
                    "active=COALESCE(active,1), price_breaks=CASE WHEN price_breaks IS NULL OR "
                    "price_breaks='' OR price_breaks='[]' THEN :pb ELSE price_breaks END "
                    "WHERE supplier_id=:s AND sku=:k"), {**_params, "k": sku})
    if commit:
        try:
            db.commit()
        except Exception:
            return {"suppliers": n_sup, "products": n_prod, "domains": n_dom}
    return {"suppliers": n_sup, "products": n_prod, "domains": n_dom}


def _seed_supplier_set(db, suppliers: List[Dict[str, Any]], supplier_skus: Dict[str, List[str]]) -> Dict[str, int]:
    """Insert/update a supplier set and active rows for the exact SKUs each supplier should carry."""
    if db is None:
        return {}
    ensure_tables(db)
    import json as _json
    import uuid
    n_sup = n_prod = n_dom = 0
    for s in suppliers:
        if not _exists(db, "SELECT 1 FROM suppliers WHERE id=:i", {"i": s["id"]}):
            db.execute(text("INSERT INTO suppliers (id, name, unit_cost, lead_time_days, moq, on_time_rate, "
                            "reliability_score, recent_sla_breaches, late_deliveries_30d, active) "
                            "VALUES (:id,:n,:c,:l,:m,:o,:r,0,0,1)"),
                       {"id": s["id"], "n": s["name"], "c": s["unit_cost"], "l": s["lead_time_days"],
                        "m": s["moq"], "o": s["on_time_rate"], "r": s["reliability_score"]})
            n_sup += 1
        else:
            db.execute(text("UPDATE suppliers SET name=:n, unit_cost=:c, lead_time_days=:l, moq=:m, "
                            "on_time_rate=:o, reliability_score=:r, active=1 WHERE id=:id"),
                       {"id": s["id"], "n": s["name"], "c": s["unit_cost"], "l": s["lead_time_days"],
                        "m": s["moq"], "o": s["on_time_rate"], "r": s["reliability_score"]})
        if not _exists(db, "SELECT 1 FROM trusted_supplier_domains WHERE domain=:d", {"d": s["domain"]}):
            db.execute(text("INSERT INTO trusted_supplier_domains (id, domain, supplier_id, added_by, active) "
                            "VALUES (:i,:d,:s,'seed',1)"),
                       {"i": str(uuid.uuid4()), "d": s["domain"], "s": s["id"]})
            n_dom += 1
        else:
            db.execute(text("UPDATE trusted_supplier_domains SET supplier_id=:s, active=1 WHERE domain=:d"),
                       {"d": s["domain"], "s": s["id"]})
        _t = s.get("terms") or {}
        _params = {"s": s["id"], "moq": _t.get("moq"), "mov": _t.get("min_order_value_cents"),
                   "lt": _t.get("lead_time_days"), "rg": _t.get("region"), "ot": _t.get("on_time_rate"),
                   "pb": _json.dumps(_t.get("price_breaks") or []), "cs": _t.get("contract_status")}
        for sku in sorted(set(supplier_skus.get(str(s["id"]), []) or [])):
            if not _exists(db, "SELECT 1 FROM supplier_products WHERE supplier_id=:s AND sku=:k",
                           {"s": s["id"], "k": sku}):
                db.execute(text(
                    "INSERT INTO supplier_products (supplier_id, sku, moq, min_order_value_cents, "
                    "lead_time_days, region, on_time_rate, price_breaks, contract_status, active) "
                    "VALUES (:s,:k,:moq,:mov,:lt,:rg,:ot,:pb,:cs,1)"), {**_params, "k": sku})
                n_prod += 1
            else:
                db.execute(text(
                    "UPDATE supplier_products SET moq=:moq, min_order_value_cents=:mov, "
                    "lead_time_days=:lt, region=:rg, on_time_rate=:ot, contract_status=:cs, "
                    "price_breaks=:pb, active=1 WHERE supplier_id=:s AND sku=:k"),
                    {**_params, "k": sku})
    return {"suppliers": n_sup, "products": n_prod, "domains": n_dom}


def _product_rows(db) -> List[Dict[str, Any]]:
    """Active products with specs, if the catalog table is present."""
    import json as _json
    try:
        rows = db.execute(text(
            "SELECT sku, name, specs FROM products WHERE COALESCE(active,1)=1 "
            "AND sku IS NOT NULL AND sku <> ''"
        )).fetchall()
    except Exception:
        try:
            rows = db.execute(text(
                "SELECT sku FROM products WHERE COALESCE(active,1)=1 "
                "AND sku IS NOT NULL AND sku <> ''"
            )).fetchall()
            return [{"sku": str(r[0]), "name": str(r[0]), "specs": {}} for r in rows if r and r[0]]
        except Exception:
            return [{"sku": s, "name": s, "specs": {}} for s in DEMO_SKUS]
    out = []
    for r in rows:
        specs = r[2]
        if isinstance(specs, str):
            try:
                specs = _json.loads(specs)
            except Exception:
                specs = {}
        out.append({"sku": str(r[0]), "name": str(r[1] or r[0]), "specs": specs if isinstance(specs, dict) else {}})
    return out


def _routing_rules() -> "tuple[List[Dict[str, Any]], str]":
    """The (rules, default_supplier_id) for seed-time supplier routing — from the StoreProfile so core
    carries NO product vocabulary. Empty rules → callers fall back to the default (or base coverage)."""
    try:
        from src.app.platform.store_profile import profile_slot
        rules = profile_slot("supplier_routing_rules", default=None) or []
        default = str(profile_slot("supplier_routing_default", default="") or "")
        return ([r for r in rules if isinstance(r, dict)], default) if isinstance(rules, list) else ([], default)
    except Exception:
        return ([], "")


def _supplier_route_for_product(sku: str, name: str = "", specs: Optional[Dict[str, Any]] = None) -> List[str]:
    """Demo routing policy: product metadata decides eligible suppliers; ranking decides the winner. The
    RULES (sku-prefix / attribute tokens → supplier) live in the StoreProfile (supplier_routing_rules), so
    this stays vertical-blind — it only matches opaque data against the profile's rules. First match wins."""
    specs = specs or {}
    s = str(sku or "").upper()
    n = str(name or "").lower()
    category = str(specs.get("category") or specs.get("product_category") or specs.get("use_case") or "").lower()
    tags = " ".join(str(t).lower() for t in (specs.get("tags") or []) if t is not None)
    blob = f"{s.lower()} {n} {category} {tags}"
    rules, default = _routing_rules()
    for rule in rules:
        sid = str(rule.get("supplier_id") or "")
        if not sid:
            continue
        prefixes = tuple(str(p).upper() for p in (rule.get("sku_prefixes") or []))
        tokens = [str(t).lower() for t in (rule.get("tokens") or [])]
        if (prefixes and s.startswith(prefixes)) or any(t in blob for t in tokens):
            return [sid]
    return [default] if default else []


def _deactivate_demo_coverage(db, skus: List[str]) -> None:
    """Disable old demo over-coverage for the SKUs we are about to route; do not touch real suppliers.

    DESIGN NOTE (replace, NOT add-alongside — do not "un-deactivate" the base suppliers): routing
    REPLACES coverage so each routed SKU resolves to exactly its category supplier. This is deliberate,
    not vestigial. The demo's value is that the draft recipient varies by category (GAM→CreatorFleet,
    MON→PeriLink); that only holds if the category supplier wins DETERMINISTICALLY. Leaving the base
    suppliers (SUP-7 @ $1115 < SUP-CREATOR @ $1260) active would let price-ranking pick the base over the
    category supplier → the draft silently goes to the wrong supplier and "who wins" becomes a function of
    seeded prices. If a genuine multi-supplier shortlist is ever wanted, express it as an ORDERED routing
    rule in the profile (primary first), not as base-supplier bleed-through."""
    for sid in sorted(_ALL_DEMO_SUPPLIER_IDS):
        for sku in skus:
            try:
                db.execute(text("UPDATE supplier_products SET active=0 WHERE supplier_id=:s AND sku=:k"),
                           {"s": sid, "k": sku})
            except Exception:
                return


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
    if db is None:
        return {}
    ensure_tables(db)
    legacy_counts = seed_demo(db, skus=[], commit=False)
    rows = _product_rows(db)
    by_sku = {r["sku"]: r for r in rows}
    for sku in DEMO_SKUS:
        by_sku.setdefault(sku, {"sku": sku, "name": sku, "specs": {}})
    skus = sorted(by_sku)
    _deactivate_demo_coverage(db, skus)
    supplier_skus: Dict[str, List[str]] = {str(s["id"]): [] for s in _ROUTED_DEMO_SUPPLIERS}
    for sku, row in by_sku.items():
        for sid in _supplier_route_for_product(sku, row.get("name") or sku, row.get("specs") or {}):
            supplier_skus.setdefault(sid, []).append(sku)
    routed_counts = _seed_supplier_set(db, _ROUTED_DEMO_SUPPLIERS, supplier_skus)
    channels_set = apply_demo_supplier_channels(db)   # stamp each demo supplier's preferred comms channel
    counts = {
        "suppliers": int(legacy_counts.get("suppliers") or 0) + int(routed_counts.get("suppliers") or 0),
        "products": int(legacy_counts.get("products") or 0) + int(routed_counts.get("products") or 0),
        "domains": int(legacy_counts.get("domains") or 0) + int(routed_counts.get("domains") or 0),
        "channels": int(channels_set),
    }
    if commit:
        try:
            db.commit()
        except Exception:
            return counts
    return counts


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


def lead_times_for_skus(db, skus: List[str]) -> Dict[str, Dict[str, Any]]:
    """Per-sku assigned supplier + its REAL lead time — the ETA for the backordered part of a split shipment.
    Picks the most reliable active supplier that carries each sku; the per-sku supplier_products.lead_time_days
    overrides the supplier default. Returns {sku: {supplier_ref, lead_time_days}}; a sku no active supplier
    carries simply has no entry (its backorder then reads "once replenished", never a fabricated ETA)."""
    out: Dict[str, Dict[str, Any]] = {}
    if db is None or not skus:
        return out
    try:
        params = {f"s{i}": str(s) for i, s in enumerate(skus)}
        placeholders = ", ".join(f":{k}" for k in params)
        rows = db.execute(text(
            f"SELECT sp.sku, s.id, COALESCE(sp.lead_time_days, s.lead_time_days) AS lt, "
            f"COALESCE(s.reliability_score, 0) AS rel "
            f"FROM suppliers s JOIN supplier_products sp ON sp.supplier_id = s.id "
            f"WHERE sp.sku IN ({placeholders}) AND COALESCE(s.active,1)=1 AND COALESCE(sp.active,1)=1"),
            params).fetchall()
    except Exception:
        return out
    best_rel: Dict[str, float] = {}
    for r in rows:
        sku = str(r[0])
        rel = float(r[3] or 0)
        if sku not in out or rel > best_rel.get(sku, -1.0):
            best_rel[sku] = rel
            out[sku] = {"supplier_ref": str(r[1]),
                        "lead_time_days": (int(r[2]) if r[2] is not None else None)}
    return out


def cheapest_wholesale_cents(db, sku: str) -> Optional[int]:
    """The lowest active-supplier wholesale for a sku, in CENTS — the economics fallback when there is
    no live validated quote (suppliers.unit_cost is stored in dollars). None if no supplier carries it."""
    if db is None or not sku:
        return None
    try:
        row = db.execute(text(
            "SELECT MIN(s.unit_cost) FROM suppliers s JOIN supplier_products sp ON sp.supplier_id = s.id "
            "WHERE sp.sku = :k AND COALESCE(s.active,1)=1 AND COALESCE(sp.active,1)=1 "
            "AND s.unit_cost IS NOT NULL"),
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
    ("Northbridge Business Systems", "northbridge-business.example", "rfq@northbridge-business.example"),
    ("CreatorFleet Wholesale", "creatorfleet.example", "quotes@creatorfleet.example"),
    ("Orchard Device Supply", "orchard-device.example", "orders@orchard-device.example"),
    ("PeriLink Accessories", "perilink-accessories.example", "sales@perilink-accessories.example"),
    ("Harbour Office Wholesale", "harbour-office.example", "quotes@harbour-office.example"),
]


def _register_or_backfill_vendor(lookup, register, backfill, *, tenant_id, name, domain, email) -> bool:
    """Ensure the demo vendor exists WITH a contact email. If the row exists but its contact is missing
    (registered earlier without one), backfill it — otherwise the draft keeps resolving the bare domain.
    Returns True when something changed (registered or backfilled)."""
    try:
        existing = lookup(tenant_id=tenant_id, domain=domain)
        if existing:
            if not str(existing.get("contact_email") or "").strip():
                return bool(backfill(tenant_id=tenant_id, domain=domain, contact_email=email))
            return False  # already complete
        res = register(tenant_id=tenant_id, legal_name=name, verified_domain=domain,
                       contact_email=email, risk_tier="low") or {}
        return bool(res.get("ok", True))
    except Exception:
        return False  # best-effort seed — observable return, never a silent swallow


def seed_demo_vendor_contacts(*, tenant_id: str = "default") -> int:
    """Register the demo suppliers as KYV vendors with a verified contact email (idempotent), and backfill
    the contact on any matching vendor that was registered earlier WITHOUT one. Returns the count of vendors
    created-or-backfilled. After this, the draft's recipient_email resolves to the contact email instead of
    the bare domain (the live-packet polish fix)."""
    try:
        from src.app.security.kyv_registry import (
            lookup_vendor_by_domain, register_vendor, set_vendor_contact_email,
        )
    except Exception:
        return 0
    return sum(1 for name, domain, email in _DEMO_VENDOR_CONTACTS
               if _register_or_backfill_vendor(lookup_vendor_by_domain, register_vendor,
                                               set_vendor_contact_email,
                                               tenant_id=tenant_id, name=name, domain=domain, email=email))


# A short prior-dealings history per demo supplier domain, as (days_ago, invoice_amount_dollars). The
# draft's evidence packet reads this (Supplier_Inbox_Reader) to show "N prior dealings, last invoice $X" —
# the "how we usually deal with them" context the operator sees before approving a send.
_DEMO_SUPPLIER_HISTORY = [
    ("approved-supplier.example", [(58, 6690.0), (33, 5575.0), (9, 7805.0)]),
    ("bulk-parts.example", [(47, 5900.0), (15, 7080.0)]),
    ("northbridge-business.example", [(44, 12350.0), (18, 18620.0), (6, 21400.0)]),
    ("creatorfleet.example", [(39, 22900.0), (21, 31100.0), (8, 44750.0)]),
    ("orchard-device.example", [(52, 8300.0), (16, 15800.0)]),
    ("perilink-accessories.example", [(31, 2400.0), (12, 3900.0), (4, 5200.0)]),
    ("harbour-office.example", [(42, 4200.0), (19, 7600.0)]),
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
