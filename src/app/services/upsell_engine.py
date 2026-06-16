from __future__ import annotations

"""Upsell / cross-sell engine.

Generates product recommendations when an item is added to cart.

Two complementary signals:
1. Co-purchase affinity (SQL) — "customers who bought X also bought Y"
2. Use-case expansion map (NLP) — "gaming laptop → gaming peripherals"

Both respect stock levels: only in-stock candidates are returned.

Design:
- Called synchronously from the cart add-item route.
- No LLM required — fast, deterministic, DB-backed.
- Results surfaced as `upsell` field in cart response.
"""

import re
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as _text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.upsell")

# ── Use-case affinity map ─────────────────────────────────────────────────────
# Maps category keywords extracted from the session query to product categories
# that are commonly needed together.

_USE_CASE_CROSS_SELL: Dict[str, List[str]] = {
    "gaming": ["gaming_mouse", "gaming_keyboard", "gaming_headset", "gaming_monitor", "gaming_chair"],
    "esports": ["gaming_mouse", "gaming_keyboard", "gaming_headset", "144hz_monitor"],
    "content_creation": ["external_ssd", "usb_hub", "webcam", "ring_light", "microphone"],
    "video_editing": ["external_ssd", "usb_hub", "color_accurate_monitor", "drawing_tablet"],
    "university": ["laptop_bag", "mouse", "external_monitor", "usb_hub", "webcam"],
    "engineering": ["external_monitor", "drawing_tablet", "usb_hub", "mechanical_keyboard"],
    "music": ["audio_interface", "studio_headphones", "microphone", "midi_controller"],
    "photography": ["external_ssd", "card_reader", "color_accurate_monitor", "drawing_tablet"],
    "streaming": ["capture_card", "ring_light", "microphone", "webcam", "green_screen"],
    "office": ["laptop_stand", "external_monitor", "wireless_keyboard", "wireless_mouse", "webcam"],
}

_USE_CASE_RE = re.compile(
    r"\b(gaming|esports|game|fps|content.creat|video.edit|3d.render|stream|"
    r"university|school|college|engineering|music.produc|photograph|office|work)\b",
    re.IGNORECASE,
)


def _detect_use_case(session_query: Optional[str]) -> Optional[str]:
    """Return the dominant use-case keyword from the session query, or None."""
    if not session_query:
        return None
    m = _USE_CASE_RE.search(session_query)
    if not m:
        return None
    raw = m.group(0).lower().replace(" ", "_").replace(".", "_")
    # Normalise
    if "gaming" in raw or "esport" in raw or "fps" in raw:
        return "gaming"
    if "content" in raw or "video" in raw or "stream" in raw:
        return "content_creation"
    if "university" in raw or "school" in raw or "college" in raw:
        return "university"
    if "engineer" in raw or "3d" in raw or "render" in raw:
        return "engineering"
    if "music" in raw:
        return "music"
    if "photo" in raw:
        return "photography"
    if "office" in raw or "work" in raw:
        return "office"
    return None


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


# ── Category-based expansion ──────────────────────────────────────────────────

def _category_expansion_candidates(
    use_case: str, exclude_skus: List[str], limit: int = 10
) -> List[str]:
    """Return SKUs matching the use-case category tags, excluding already-carted items."""
    tags = _USE_CASE_CROSS_SELL.get(use_case, [])
    if not tags:
        return []
    try:
        exclude_params = {f"e{i}": s for i, s in enumerate(exclude_skus)} if exclude_skus else {}
        tag_params = {f"t{i}": t for i, t in enumerate(tags[:8])}
        conditions = " OR ".join(f"LOWER(p.category) LIKE '%' || :{k} || '%'" for k in tag_params)
        exclude_clause = (
            f"AND p.sku NOT IN ({', '.join(f':{k}' for k in exclude_params)})"
            if exclude_params else ""
        )
        sql = (
            f"SELECT p.sku FROM products p "
            f"WHERE COALESCE(p.active, 1) = 1 "
            f"AND ({conditions}) "
            f"{exclude_clause} "
            f"LIMIT :lim"
        )
        params = {**tag_params, **exclude_params, "lim": limit}
        with db_session() as db:
            rows = db.execute(_text(sql), params).fetchall()
        return [str(r[0]) for r in rows]
    except Exception as exc:
        logger.debug("_category_expansion_candidates failed: %s", exc)
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

    # Step 2: Use-case expansion (legacy; relies on p.category which the demo schema
    # lacks, so usually empty — kept for stores that DO have a category column).
    use_case = _detect_use_case(session_query)
    uc_skus: List[str] = []
    if use_case:
        uc_skus = _category_expansion_candidates(use_case, exclude_skus=exclude_skus + co_skus, limit=10)

    # Step 2b: Companion-TYPE expansion (classifier-driven; schema-free). When a laptop
    # is carted, pull the accessory types that complete it (bag/audio/storage/...).
    comp_skus: List[str] = []
    added_type = _product_type_for_sku(added_sku)
    if added_type:
        comp_skus = _companion_type_candidates(
            added_type, exclude_skus=exclude_skus + co_skus + uc_skus, limit=10
        )

    # Step 3: Fetch stock levels for all candidates
    all_candidate_skus = list(dict.fromkeys(co_skus + uc_skus + comp_skus))[:30]
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
            p["reason"] = f"Popular for {use_case.replace('_', ' ')} setups" if use_case else "You might also need"

    # Sort: co-purchase items first, then use-case items
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
