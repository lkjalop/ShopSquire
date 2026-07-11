"""T0 catalog read-model facade (V2 Phase 1) — ONE read API over the two catalog models.

The split this converges (roadmap docs/SHOPSQUIRE_V2_GREENFIELD_ROADMAP_2026-07-10.md §1d):
  • legacy  — `products` (+ `inventory`): what suggest()/fulfillment read today. Rich read
              surface (specs/product_type/brand/category), price embedded on the row.
  • canonical — `product`/`variant` (identity) + `price_book_entry` (price) +
              `inventory_level` (stock): what platform adapters (Shopify/Magento) write.

The V2 recommendation_core reads ONLY this facade — never a table directly — so retrieval
logic is written once against VariantView and the storage cutover (legacy → canonical) is a
mode flip, not a rewrite. Legacy suggest() is NOT touched by this module.

Mode (env CATALOG_READ_MODEL, then feature_flags.json, default "legacy"):
  legacy    — read products/inventory (today's truth). DEFAULT.
  canonical — read variant/price_book_entry/inventory_level.
  dual      — serve LEGACY (authoritative), also read canonical and count divergence —
              the same measure-before-promote discipline as RECOMMEND_RETRIEVAL_MODE.
coverage_report(db) quantifies the convergence gap (missing SKUs, price/stock drift) so
the legacy→canonical backfill and the eventual flip are MEASURED decisions.

Vertical-blind: no field here assumes electronics. taxonomy_node_id is the T1 slot —
populated by product_classification once the taxonomy registry lands; None until then.
Best-effort like its neighbours: never raises into a caller; empty/None on any failure.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.catalog_read_model")

DEFAULT_TENANT = "default"
_MODES = ("legacy", "canonical", "dual")


def read_model_mode() -> str:
    raw = str(os.getenv("CATALOG_READ_MODEL", "") or "").strip().lower()
    if raw in _MODES:
        return raw
    try:
        from src.app.config import get_settings
        with open(get_settings().feature_flags_path, "r", encoding="utf-8") as f:
            raw = str(json.load(f).get("CATALOG_READ_MODEL") or "").strip().lower()
        if raw in _MODES:
            return raw
    except Exception:
        pass
    return "legacy"


@dataclass(frozen=True)
class VariantView:
    """The one shape V2 retrieval/ranking sees, whichever store served it."""
    sku: str
    title: str = ""
    brand: str = ""
    category: str = ""
    product_type: str = ""
    price_cents: Optional[int] = None
    currency: str = "USD"
    specs: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    stock: Optional[int] = None
    # STOCK SYSTEM-OF-RECORD DECISION (2026-07-11, GPT-5.6 #9; 89/114 SKUs drift between the
    # two stock tables): canonical inventory_level is the TARGET SoR (multi-location,
    # reserved/available semantics — the only shape that prevents overselling); the legacy
    # `inventory` table remains what legacy suggest() reads until its retirement. V2 reads
    # availability ONLY through this facade in canonical mode. Every stock value carries
    # provenance + freshness so parity divergences are attributable, never mysterious.
    stock_source: Optional[str] = None      # "inventory_level" | "legacy_inventory"
    stock_as_of: Optional[str] = None       # max(updated_at) of the contributing rows
    active: bool = True
    image_url: str = ""
    taxonomy_node_id: Optional[str] = None  # T1 slot — product_classification fills this
    source: str = "legacy"


def _loads(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw) if raw else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


# ── legacy adapter (products + inventory) ─────────────────────────────────────

def _legacy_row_to_view(row: Any, stock: Optional[int]) -> VariantView:
    return VariantView(
        sku=str(row[0]), title=str(row[1] or ""), brand=str(row[2] or ""),
        category=str(row[3] or ""), product_type=str(row[4] or ""),
        price_cents=int(row[5]) if row[5] is not None else None,
        currency=str(row[6] or "USD"), specs=_loads(row[7]), attributes=_loads(row[8]),
        active=bool(row[9] if row[9] is not None else 1), image_url=str(row[10] or ""),
        stock=stock, source="legacy",
    )


_LEGACY_COLS = ("p.sku, p.name, p.brand, p.category, p.product_type, p.price_cents, "
                "p.currency, p.specs, p.attributes, p.active, p.image_url")


def _legacy_stock(db, product_sku: str) -> Tuple[Optional[int], Optional[str]]:
    """(stock, as_of) from the legacy inventory table — what legacy suggest() sees."""
    try:
        row = db.execute(text(
            "SELECT COALESCE(SUM(i.stock), 0), MAX(i.updated_at) FROM inventory i "
            "JOIN products p ON p.id = i.product_id WHERE p.sku = :s"), {"s": product_sku}).fetchone()
        if row and row[0] is not None:
            return int(row[0]), (str(row[1]) if row[1] else None)
        return None, None
    except Exception:
        return None, None


def _legacy_get(db, sku: str) -> Optional[VariantView]:
    try:
        row = db.execute(text(
            f"SELECT {_LEGACY_COLS} FROM products p WHERE p.sku = :s LIMIT 1"), {"s": sku}).fetchone()
        if not row:
            return None
        stock, as_of = _legacy_stock(db, sku)
        view = _legacy_row_to_view(row, stock)
        return VariantView(**{**view.__dict__, "stock_source": "legacy_inventory" if stock is not None else None,
                              "stock_as_of": as_of})
    except Exception:
        return None


def _legacy_search(db, *, text_query: Optional[str], brand: Optional[str], category: Optional[str],
                   product_type: Optional[str], min_price_cents: Optional[int],
                   max_price_cents: Optional[int], limit: int) -> List[VariantView]:
    try:
        clauses, params = ["COALESCE(p.active,1)=1"], {"lim": max(1, min(int(limit), 500))}
        if text_query:
            clauses.append("(LOWER(p.name) LIKE :q OR LOWER(p.category) LIKE :q OR "
                           "LOWER(p.product_type) LIKE :q OR LOWER(p.brand) LIKE :q)")
            params["q"] = f"%{str(text_query).strip().lower()}%"
        if brand:
            clauses.append("LOWER(p.brand) = :br"); params["br"] = str(brand).lower()
        if category:
            clauses.append("LOWER(p.category) = :ca"); params["ca"] = str(category).lower()
        if product_type:
            clauses.append("LOWER(p.product_type) = :pt"); params["pt"] = str(product_type).lower()
        if min_price_cents is not None:
            clauses.append("p.price_cents >= :pmin"); params["pmin"] = int(min_price_cents)
        if max_price_cents is not None:
            clauses.append("p.price_cents <= :pmax"); params["pmax"] = int(max_price_cents)
        rows = db.execute(text(
            f"SELECT {_LEGACY_COLS} FROM products p WHERE {' AND '.join(clauses)} "
            "ORDER BY p.price_cents ASC LIMIT :lim"), params).fetchall()
        return [_legacy_row_to_view(r, None) for r in rows]  # stock resolved lazily per-sku
    except Exception:
        return []


# ── canonical adapter (variant + price_book_entry + inventory_level) ─────────

def _canonical_get(db, sku: str, *, tenant_id: str = DEFAULT_TENANT) -> Optional[VariantView]:
    try:
        row = db.execute(text(
            "SELECT v.sku, COALESCE(pr.title,''), COALESCE(pr.brand,''), COALESCE(pr.category,''), "
            "v.attributes_json, pr.attributes_json, v.status "
            "FROM variant v LEFT JOIN product pr ON pr.id = v.product_id AND pr.tenant_id = v.tenant_id "
            "WHERE v.tenant_id = :t AND v.sku = :s LIMIT 1"),
            {"t": tenant_id, "s": sku}).fetchone()
        if not row:
            return None
        price = db.execute(text(
            "SELECT COALESCE(sale_cents, list_cents), currency FROM price_book_entry "
            "WHERE tenant_id = :t AND sku = :s AND channel = 'default' "
            "ORDER BY updated_at DESC LIMIT 1"), {"t": tenant_id, "s": sku}).fetchone()
        stock = db.execute(text(
            "SELECT SUM(COALESCE(available, on_hand - reserved, on_hand)), MAX(updated_at) "
            "FROM inventory_level WHERE tenant_id = :t AND sku = :s"),
            {"t": tenant_id, "s": sku}).fetchone()
        v_attrs, p_attrs = _loads(row[4]), _loads(row[5])
        has_stock = stock and stock[0] is not None
        return VariantView(
            sku=str(row[0]), title=str(row[1]), brand=str(row[2]), category=str(row[3]),
            product_type=str(v_attrs.get("product_type") or p_attrs.get("product_type") or ""),
            price_cents=int(price[0]) if price and price[0] is not None else None,
            currency=str(price[1]) if price and price[1] else "AUD",
            specs=_loads(v_attrs.get("specs")) or v_attrs, attributes=p_attrs,
            stock=int(stock[0]) if has_stock else None,
            stock_source="inventory_level" if has_stock else None,
            stock_as_of=(str(stock[1]) if has_stock and stock[1] else None),
            active=(str(row[6] or "active") == "active"), source="canonical",
        )
    except Exception:
        return None


def _canonical_search(db, *, text_query: Optional[str], brand: Optional[str], category: Optional[str],
                      product_type: Optional[str], min_price_cents: Optional[int],
                      max_price_cents: Optional[int], limit: int,
                      tenant_id: str = DEFAULT_TENANT) -> List[VariantView]:
    try:
        clauses = ["v.tenant_id = :t", "v.status = 'active'"]
        params: Dict[str, Any] = {"t": tenant_id, "lim": max(1, min(int(limit), 500))}
        if text_query:
            clauses.append("(LOWER(pr.title) LIKE :q OR LOWER(pr.category) LIKE :q OR LOWER(pr.brand) LIKE :q)")
            params["q"] = f"%{str(text_query).strip().lower()}%"
        if brand:
            clauses.append("LOWER(pr.brand) = :br"); params["br"] = str(brand).lower()
        if category:
            clauses.append("LOWER(pr.category) = :ca"); params["ca"] = str(category).lower()
        rows = db.execute(text(
            "SELECT v.sku FROM variant v "
            "LEFT JOIN product pr ON pr.id = v.product_id AND pr.tenant_id = v.tenant_id "
            f"WHERE {' AND '.join(clauses)} LIMIT :lim"), params).fetchall()
        out: List[VariantView] = []
        for r in rows:
            view = _canonical_get(db, str(r[0]), tenant_id=tenant_id)
            if view is None:
                continue
            if product_type and view.product_type.lower() != str(product_type).lower():
                continue
            if min_price_cents is not None and (view.price_cents is None or view.price_cents < min_price_cents):
                continue
            if max_price_cents is not None and (view.price_cents is None or view.price_cents > max_price_cents):
                continue
            out.append(view)
        return sorted(out, key=lambda v: (v.price_cents is None, v.price_cents or 0))
    except Exception:
        return []


# ── the facade ────────────────────────────────────────────────────────────────

def get_variant(db, sku: str, *, tenant_id: str = DEFAULT_TENANT,
                mode: Optional[str] = None) -> Optional[VariantView]:
    if db is None or not sku:
        return None
    m = mode if mode in _MODES else read_model_mode()
    if m == "canonical":
        return _canonical_get(db, sku, tenant_id=tenant_id)
    view = _legacy_get(db, sku)
    if m == "dual":
        other = _canonical_get(db, sku, tenant_id=tenant_id)
        _log_divergence(sku, view, other)
    return view


def search_variants(db, *, text_query: Optional[str] = None, brand: Optional[str] = None,
                    category: Optional[str] = None, product_type: Optional[str] = None,
                    min_price_cents: Optional[int] = None, max_price_cents: Optional[int] = None,
                    limit: int = 50, tenant_id: str = DEFAULT_TENANT,
                    mode: Optional[str] = None) -> List[VariantView]:
    if db is None:
        return []
    m = mode if mode in _MODES else read_model_mode()
    kw = dict(text_query=text_query, brand=brand, category=category, product_type=product_type,
              min_price_cents=min_price_cents, max_price_cents=max_price_cents, limit=limit)
    if m == "canonical":
        return _canonical_search(db, tenant_id=tenant_id, **kw)
    views = _legacy_search(db, **kw)
    if m == "dual":
        other = _canonical_search(db, tenant_id=tenant_id, **kw)
        if {v.sku for v in views} != {v.sku for v in other}:
            logger.info("catalog_read_model dual search divergence: legacy=%d canonical=%d (query=%r)",
                        len(views), len(other), text_query)
    return views


def _log_divergence(sku: str, legacy: Optional[VariantView], canonical: Optional[VariantView]) -> None:
    if legacy is None and canonical is None:
        return
    if (legacy is None) != (canonical is None):
        logger.info("catalog_read_model dual divergence sku=%s: present_legacy=%s present_canonical=%s",
                    sku, legacy is not None, canonical is not None)
        return
    if legacy.price_cents != canonical.price_cents:
        logger.info("catalog_read_model dual price divergence sku=%s: legacy=%s canonical=%s",
                    sku, legacy.price_cents, canonical.price_cents)


def coverage_report(db, *, tenant_id: str = DEFAULT_TENANT, sample: int = 500) -> Dict[str, Any]:
    """The T0 convergence gap, quantified: which SKUs each store knows, and where price/stock
    drift. This report is the promotion gate for CATALOG_READ_MODEL=canonical — flip only when
    missing_in_canonical is empty and drift is explained."""
    out: Dict[str, Any] = {"mode": read_model_mode()}
    try:
        legacy_skus = {str(r[0]) for r in db.execute(text(
            "SELECT sku FROM products WHERE COALESCE(active,1)=1 AND sku IS NOT NULL")).fetchall()}
    except Exception:
        legacy_skus = set()
    try:
        canonical_skus = {str(r[0]) for r in db.execute(text(
            "SELECT sku FROM variant WHERE tenant_id = :t AND status = 'active'"),
            {"t": tenant_id}).fetchall()}
    except Exception:
        canonical_skus = set()
    both = sorted(legacy_skus & canonical_skus)[: max(0, int(sample))]
    price_drift, stock_drift, read_failures = [], [], []
    for sku in both:
        lv, cv = _legacy_get(db, sku), _canonical_get(db, sku, tenant_id=tenant_id)
        if lv is None or cv is None:
            # a read failure is NOT "no drift" — count it or the report lies (the
            # silent-swallow class: a broken canonical adapter would score zero drift)
            read_failures.append({"sku": sku, "legacy_ok": lv is not None, "canonical_ok": cv is not None})
            continue
        if lv.price_cents != cv.price_cents:
            price_drift.append({"sku": sku, "legacy": lv.price_cents, "canonical": cv.price_cents})
        if lv.stock is not None and cv.stock is not None and lv.stock != cv.stock:
            stock_drift.append({"sku": sku, "legacy": lv.stock, "canonical": cv.stock})
    out.update({
        "legacy_count": len(legacy_skus), "canonical_count": len(canonical_skus),
        "overlap": len(legacy_skus & canonical_skus),
        "missing_in_canonical": sorted(legacy_skus - canonical_skus)[:25],
        "missing_in_canonical_count": len(legacy_skus - canonical_skus),
        "missing_in_legacy": sorted(canonical_skus - legacy_skus)[:25],
        "missing_in_legacy_count": len(canonical_skus - legacy_skus),
        "price_drift": price_drift[:25], "price_drift_count": len(price_drift),
        "stock_drift": stock_drift[:25], "stock_drift_count": len(stock_drift),
        "read_failures": read_failures[:25], "read_failure_count": len(read_failures),
    })
    # CLASSIFICATION FRESHNESS (census 3 root cause, 2026-07-12): active SKUs without a
    # classification row are INVISIBLE to taxonomy-first retrieval — reactivated/new products
    # must alarm here (>0 = run the onboarding classify), never silently vanish from V2.
    try:
        from src.app.services.taxonomy_registry import ensure_tables as _tax_tables
        _tax_tables(db)
        out["unclassified_active_count"] = int(db.execute(text(
            "SELECT COUNT(*) FROM products p WHERE COALESCE(p.active,1)=1 AND p.sku NOT IN "
            "(SELECT sku FROM product_classification WHERE tenant_id = :t)"),
            {"t": tenant_id}).fetchone()[0])
    except Exception:
        out["unclassified_active_count"] = None  # unknown must not read as zero
    return out


def backfill_canonical_from_legacy(db, *, tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> Dict[str, int]:
    """One-way legacy→canonical convergence: upsert every active legacy product into
    product/variant + price_book_entry so the canonical side reaches parity without touching
    the legacy tables suggest() reads. Idempotent (natural-key upserts). Stock is NOT
    backfilled — inventory_level stays owned by its own seeding/sync (double-writing stock
    from two sources is how overselling starts)."""
    from src.app.services.catalog_entities import upsert_product, upsert_variant
    from src.app.services.commerce_catalog import upsert_price
    stats = {"products": 0, "variants": 0, "prices": 0}
    try:
        rows = db.execute(text(
            f"SELECT {_LEGACY_COLS}, p.id FROM products p "
            "WHERE COALESCE(p.active,1)=1 AND p.sku IS NOT NULL")).fetchall()
    except Exception:
        return stats
    for r in rows:
        sku, pid = str(r[0]), str(r[11])
        attrs = {"product_type": str(r[4] or ""), "specs": _loads(r[7]),
                 **_loads(r[8]), "image_url": str(r[10] or "")}
        if upsert_product(db, product_id=pid, title=str(r[1] or ""), brand=str(r[2] or ""),
                          category=str(r[3] or ""), attributes=attrs, tenant_id=tenant_id):
            stats["products"] += 1
        if upsert_variant(db, sku=sku, product_id=pid,
                          attributes={"product_type": str(r[4] or ""), "specs": _loads(r[7])},
                          tenant_id=tenant_id):
            stats["variants"] += 1
        try:
            if r[5] is not None and upsert_price(db, sku=sku, list_cents=int(r[5]),
                                                 currency=str(r[6] or "USD"), source="legacy_backfill",
                                                 tenant_id=tenant_id):
                stats["prices"] += 1
        except Exception:
            pass
    if commit:
        try:
            db.commit()
        except Exception as exc:
            logger.debug("backfill commit failed: %s", exc)
    return stats
