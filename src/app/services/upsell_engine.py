from __future__ import annotations

"""Upsell / cross-sell engine (vertical-agnostic — flavour comes from the StoreProfile).

Generates companion recommendations when an item is added to cart, from two complementary signals:
1. Co-purchase affinity (SQL) — "customers who bought X also bought Y" (data-driven, vertical-blind).
2. Companion-type expansion — a carted product's TYPE → its companion types, sourced from the
   profile `upsell_companions` slot via product_classifier.companion_types_for (electronics pairs a
   primary device with bag/audio/storage; pharmacy pairs medicine with first_aid/device; fashion
   pairs shoes with sock/belt). No vertical literal lives in this module.

Both respect stock levels: only in-stock candidates are returned.

Design:
- Called synchronously from the cart add-item route.
- No LLM required — fast, deterministic, DB-backed.
- Results surfaced as `upsell` field in cart response.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as _text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.upsell")

# NOTE (P2 flavour excision): the legacy use-case cross-sell map (use-case → category tags) was
# REMOVED — it carried vertical literals AND relied on a `products.category` column the schema
# lacks, so it was inert. The agnostic, profile-keyed companion path (_companion_type_candidates →
# product_classifier.companion_types_for ← profile upsell_companions) supersedes it for every
# vertical. A store that genuinely has a category column should re-add it as a PROFILE slot, not an
# inline map.


# ── Co-purchase affinity lookup ───────────────────────────────────────────────

def _co_purchase_candidates(sku: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Return SKUs frequently co-purchased with *sku*, with co-purchase counts."""
    try:
        with db_session() as db:
            rows = db.execute(
                _text(
                    "SELECT oi2.sku, COUNT(*) AS co_count "
                    "FROM orders_items oi1 "
                    "JOIN orders_items oi2 ON oi1.order_id = oi2.order_id AND oi2.sku != oi1.sku "
                    "JOIN products p ON p.sku = oi2.sku AND COALESCE(p.active, 1) = 1 "
                    "WHERE oi1.sku = :sku "
                    "GROUP BY oi2.sku ORDER BY co_count DESC LIMIT :lim"
                ),
                {"sku": str(sku), "lim": int(limit)},
            ).fetchall()
        return [{"sku": str(r[0]), "co_count": int(r[1])} for r in rows]
    except Exception as exc:
        logger.debug("co_purchase_candidates(%s) failed: %s", sku, exc)
        return []


# ── Product detail hydration ──────────────────────────────────────────────────

def _hydrate_candidates(skus: List[str], stock_map: Dict[str, int]) -> List[Dict[str, Any]]:
    """Return product detail rows for *skus* that are currently in stock."""
    if not skus:
        return []
    try:
        params = {f"s{i}": s for i, s in enumerate(skus)}
        placeholders = ", ".join(f":{k}" for k in params)
        # NOTE: the products schema has no `brand` column (only sku/name/price_cents/
        # image_url/specs) — selecting it threw and silently zeroed every upsell. Brand
        # is derived from the name's leading token instead.
        with db_session() as db:
            rows = db.execute(
                _text(
                    f"SELECT sku, name, price_cents, image_url "
                    f"FROM products WHERE sku IN ({placeholders}) AND COALESCE(active, 1) = 1"
                ),
                params,
            ).fetchall()
        out = []
        for r in rows:
            sku = str(r[0])
            stock = stock_map.get(sku, 0)
            if stock == 0:
                continue  # Only surface in-stock items
            name = str(r[1] or "")
            out.append({
                "sku": sku,
                "name": name,
                "brand": name.split()[0] if name.split() else "",
                "price_cents": int(r[2] or 0),
                "image_url": str(r[3] or ""),
                "stock": stock,
            })
        return out
    except Exception as exc:
        logger.debug("_hydrate_candidates failed: %s", exc)
        return []


# ── Companion-type expansion (product_type classifier) ───────────────────────
# The schema has no `category` column, so the use-case SQL above silently returns
# nothing. This path uses the agnostic-core classifier instead: once a PRIMARY item
# (laptop) is carted, surface the accessory TYPES that complete it (bag/audio/storage
# /monitor/peripheral). Classification is by product name (bounded scan), so it needs
# no schema change. The same taxonomy that EXCLUDES these from laptop search results
# routes them here, to the cart, where they belong.

def _product_type_for_sku(sku: str) -> Optional[str]:
    try:
        from src.app.services.product_classifier import classify_product_type
        with db_session() as db:
            row = db.execute(
                _text("SELECT name FROM products WHERE sku = :s LIMIT 1"), {"s": sku}
            ).fetchone()
        return classify_product_type(row[0]) if row else None
    except Exception as exc:
        logger.debug("_product_type_for_sku failed: %s", exc)
        return None


def _companion_type_candidates(
    added_type: str, exclude_skus: List[str], limit: int = 10
) -> List[str]:
    """In-stock SKUs whose product_type is a cart companion for *added_type*
    (laptop -> bag/audio/storage/monitor/peripheral/networking)."""
    try:
        from src.app.services.product_classifier import (
            classify_product_type,
            companion_types_for,
        )
        wanted = set(companion_types_for(added_type))
        if not wanted:
            return []
        excl = set(exclude_skus or [])
        with db_session() as db:
            rows = db.execute(
                _text("SELECT sku, name FROM products WHERE COALESCE(active, 1) = 1 LIMIT 500")
            ).fetchall()
        out: List[str] = []
        for sku, name in rows:
            sku = str(sku)
            if sku in excl:
                continue
            if classify_product_type(name) in wanted:
                out.append(sku)
                if len(out) >= limit:
                    break
        return out
    except Exception as exc:
        logger.debug("_companion_type_candidates failed: %s", exc)
        return []


# ── Public entry point ────────────────────────────────────────────────────────

def get_upsell_candidates(
    added_sku: str,
    cart_skus: List[str],
    session_query: Optional[str] = None,
    max_results: int = 3,
) -> List[Dict[str, Any]]:
    """Return up to *max_results* upsell candidates for a just-added SKU.

    Algorithm:
    1. Co-purchase affinity from order history (best signal)
    2. Use-case category expansion (good signal when co-purchase data is sparse)
    3. Deduplicate + filter OOS + filter already-in-cart
    4. Return top-N

    Returns a list of product dicts with: sku, name, brand, price_cents, stock, reason.
    """
    exclude_skus = list(set([added_sku] + cart_skus))

    # Step 1: Co-purchase candidates
    co_raw = _co_purchase_candidates(added_sku, limit=20)
    co_skus = [c["sku"] for c in co_raw if c["sku"] not in exclude_skus]

    # Step 2: Companion-TYPE expansion (classifier-driven; schema-free, PROFILE-keyed). When a
    # primary item is carted, pull the companion TYPES that complete it via the agnostic path
    # (product_classifier.companion_types_for ← profile upsell_companions): electronics →
    # bag/audio/storage; pharmacy → first_aid/device; fashion → sock/belt. No vertical literal here.
    comp_skus: List[str] = []
    added_type = _product_type_for_sku(added_sku)
    if added_type:
        comp_skus = _companion_type_candidates(
            added_type, exclude_skus=exclude_skus + co_skus, limit=10
        )

    # Step 3: Fetch stock levels for all candidates
    all_candidate_skus = list(dict.fromkeys(co_skus + comp_skus))[:30]
    if not all_candidate_skus:
        return []

    try:
        from src.app.services.inventory_query_service import batch_stock_levels
        stock_map = batch_stock_levels(all_candidate_skus)
    except Exception:
        stock_map = {}

    # Step 4: Hydrate + score
    hydrated = _hydrate_candidates(all_candidate_skus, stock_map)

    # Assign reason label
    co_sku_set = set(co_skus)
    comp_sku_set = set(comp_skus)
    for p in hydrated:
        if p["sku"] in co_sku_set:
            p["reason"] = "Frequently bought together"
        elif p["sku"] in comp_sku_set:
            p["reason"] = "Completes your setup"
        else:
            p["reason"] = "You might also need"

    # Sort: co-purchase items first, then companion items
    hydrated.sort(key=lambda p: (0 if p["sku"] in co_sku_set else 1, -p.get("stock", 0)))

    # Diversify companion picks by type so the buyer sees a varied set (bag + monitor +
    # audio + storage), not four bags. Co-purchase items are exempt (they're the signal).
    try:
        from src.app.services.product_classifier import classify_product_type
        per_type: Dict[str, int] = {}
        diversified: List[Dict[str, Any]] = []
        for p in hydrated:
            if p["sku"] in co_sku_set:
                diversified.append(p)
                continue
            t = classify_product_type(p.get("name"))
            if per_type.get(t, 0) >= 2:
                continue
            per_type[t] = per_type.get(t, 0) + 1
            diversified.append(p)
        hydrated = diversified
    except Exception:
        pass

    return hydrated[:max_results]
