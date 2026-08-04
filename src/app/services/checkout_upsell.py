from __future__ import annotations

import json
import logging
import re
import os
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from src.app.platform.tenant_context import current_tenant_id as _ct  # R10.2

from src.app.services.product_taxonomy import (
    ACCESSORY_FAMILIES,
    infer_accessory_slug,
    infer_product_family,
    product_tags,
)

logger = logging.getLogger("shopsquire.checkout_upsell")


_SUSPICIOUS_NAME_PAT = re.compile(
    r"(?i)(ignore\s+previous|jailbreak|system\s+prompt|developer\s+mode|override|drop\s+table|<script)"
)

# Adaptive price-guard crossover. cart_price and candidate price are BOTH in CENTS.
# Above this, the cart is "substantial" → only show upsells priced <= 70% of cart total.
# At/below this, the cart is "low-value" → allow upsells up to 1.9x the cart (an accessory
# cart can be grown). The literal 1200 here was a cents/dollars bug ($12, not $1200): every
# real cart exceeded it, so the strict branch ALWAYS fired and the relaxed branch was dead.
# $200 keeps laptop carts in the strict branch (unchanged) while reviving the relaxed branch
# for genuine accessory carts. This is the ELECTRONICS fallback; the live value is the active
# StoreProfile `cart_crossover_cents` slot (see _cart_crossover_cents) so a low-AOV vertical
# (e.g. pharmacy) or high-AOV vertical tunes the strict/relaxed boundary without code changes.
_ADAPTIVE_CART_CROSSOVER_CENTS = 20000  # $200.00


def _cart_crossover_cents(profile_id: str | None = None) -> int:
    """Adaptive price-guard crossover (cents) for the ACTIVE vertical. Prefers the StoreProfile
    `cart_crossover_cents` slot; falls back to the electronics default. profile_slot is defensive
    (never raises) so no try/except is needed (keeps this off the silent-except ratchet)."""
    from src.app.platform.store_profile import profile_slot
    val = profile_slot("cart_crossover_cents", profile_id=profile_id, default=None)
    if isinstance(val, (int, float)) and val > 0:
        return int(val)
    return _ADAPTIVE_CART_CROSSOVER_CENTS


def _passes_price_guard(price_cents: int, cart_price_cents: int) -> bool:
    """Adaptive upsell price guard. All values in CENTS.

    - Substantial cart (> crossover): accept only upsells priced <= 70% of cart total
      (don't upsell something nearly as expensive as the whole cart).
    - Low-value cart (0 < cart <= crossover): accept upsells up to 1.9x the cart
      (an accessory cart can reasonably be grown).
    - Unknown/zero cart: no guard.
    """
    crossover = _cart_crossover_cents()
    if cart_price_cents > crossover:
        return price_cents <= int(cart_price_cents * 0.7)
    if 0 < cart_price_cents <= crossover:
        return price_cents <= int(cart_price_cents * 1.9)
    return True


@dataclass
class UpsellCandidate:
    sku: str
    name: str
    price_cents: int
    stock: int
    score: float
    tags: list[str]
    reasons: list[str]
    factors: dict[str, float]
    reason_codes: list[dict[str, Any]]
    confidence: float
    model_source: str


_SKU_FAMILY_PAT = re.compile(r"^SYN-([A-Z]+)-", re.IGNORECASE)

# ELECTRONICS fallback for persona → preferred accessory slugs. Live source is the active
# StoreProfile `persona_accessory_slugs` slot (see _persona_accessory_slugs), so a fashion or
# pharmacy vertical supplies its own persona→accessory affinities instead of inheriting laptops.
_PERSONA_ACCESSORY_SLUGS: dict[str, set[str]] = {
    "student": {"laptop_sleeve", "mouse", "power_bank", "usb_hub", "dock"},
    "gamer": {"gaming_mouse", "headset", "cooling_pad", "laptop_stand", "monitor"},
    "creator": {"external_ssd", "monitor", "card_reader", "audio_interface", "dock"},
    "office": {"dock", "monitor", "headset", "compact_charger", "usb_hub"},
    "corporate": {"dock", "monitor", "headset", "compact_charger", "laptop_sleeve"},
    "engineer": {"dock", "monitor", "external_ssd", "mouse", "usb_hub"},
}


def _persona_accessory_slugs(profile_id: str | None = None) -> dict[str, set[str]]:
    """Persona → preferred accessory slugs for the ACTIVE vertical. Prefers the StoreProfile
    `persona_accessory_slugs` slot (values may be lists in JSON → normalized to sets); falls back
    to the electronics table. profile_slot is defensive, so no try/except (off the ratchet)."""
    from src.app.platform.store_profile import profile_slot
    prof = profile_slot("persona_accessory_slugs", profile_id=profile_id, default=None)
    if isinstance(prof, dict) and prof:
        out: dict[str, set[str]] = {}
        for k, v in prof.items():
            if isinstance(v, (list, set, tuple)):
                out[str(k).strip().lower()] = {str(s).strip().lower() for s in v if str(s).strip()}
        if out:
            return out
    return _PERSONA_ACCESSORY_SLUGS


def _sku_family(sku: str | None) -> str:
    s = str(sku or "").strip().upper()
    m = _SKU_FAMILY_PAT.match(s)
    if m:
        return str(m.group(1) or "").upper()
    return infer_product_family(sku=s)


# ELECTRONICS-centric fallback: intent family_code -> trigger keywords. Live source is the active
# StoreProfile `intent_family_keywords` slot. Insertion order IS precedence: the first family whose
# keyword appears in the (query+persona+use_case) text wins (LAP before FSH before HMW).
_INTENT_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "LAP": ("laptop", "macbook", "notebook", "gaming", "student", "university", "office pc", "windows"),
    "FSH": ("shirt", "dress", "fashion", "sneaker", "hoodie", "clothes", "apparel"),
    "HMW": ("kitchen", "home", "bedroom", "lamp", "basket", "decor", "furniture"),
}


def _intent_family_keywords(profile_id: str | None = None) -> dict[str, tuple[str, ...]]:
    """family_code -> trigger keywords for the ACTIVE vertical. Prefers the StoreProfile
    `intent_family_keywords` slot; falls back to the electronics map. profile_slot is defensive."""
    from src.app.platform.store_profile import profile_slot
    prof = profile_slot("intent_family_keywords", profile_id=profile_id, default=None)
    if isinstance(prof, dict) and prof:
        out: dict[str, tuple[str, ...]] = {}
        for fam, kws in prof.items():
            if isinstance(kws, (list, tuple)):
                tok = tuple(str(k).strip().lower() for k in kws if str(k).strip())
                if tok:
                    out[str(fam).strip().upper()] = tok
        if out:
            return out
    return _INTENT_FAMILY_KEYWORDS


def _infer_intent_family(query: str | None, persona: str | None, use_case: str | None) -> str | None:
    text = " ".join([
        str(query or "").strip().lower(),
        str(persona or "").strip().lower(),
        str(use_case or "").strip().lower(),
    ]).strip()
    if not text:
        return None
    for fam, kws in _intent_family_keywords().items():
        if any(t in text for t in kws):
            return fam
    return None


# ELECTRONICS-centric fallback complement matrix (cart_family -> {candidate_family: weight}).
# Live source is the active StoreProfile `family_complement_matrix` slot. Same-family gets the
# highest weight; accessory/peripheral families complement LAP strongly (a shopper with a laptop
# needs a mouse/headset/bag, not another laptop).
_FAMILY_COMPLEMENT_MATRIX: dict[str, dict[str, float]] = {
    "LAP": {"LAP": 1.0, "PERIPH": 0.95, "ACC": 0.90, "MON": 0.90, "HEAD": 0.85, "COOL": 0.80, "BAG": 0.75, "HMW": 0.35, "FSH": 0.05},
    "FSH": {"FSH": 1.0, "HMW": 0.25, "LAP": 0.10},
    "HMW": {"HMW": 1.0, "FSH": 0.30, "LAP": 0.20},
    "PERIPH": {"PERIPH": 0.80, "LAP": 0.60, "ACC": 0.70, "HEAD": 0.65, "MON": 0.55, "HMW": 0.20, "FSH": 0.05},
    "MON": {"MON": 0.80, "LAP": 0.65, "PERIPH": 0.70, "ACC": 0.60, "HMW": 0.20, "FSH": 0.05},
}


def _family_complement_matrix(profile_id: str | None = None) -> dict[str, dict[str, float]]:
    """cart_family -> {candidate_family: weight} for the ACTIVE vertical. Prefers the StoreProfile
    `family_complement_matrix` slot; falls back to the electronics matrix. profile_slot is defensive."""
    from src.app.platform.store_profile import profile_slot
    prof = profile_slot("family_complement_matrix", profile_id=profile_id, default=None)
    if isinstance(prof, dict) and prof:
        out: dict[str, dict[str, float]] = {}
        for cart_fam, row in prof.items():
            if isinstance(row, dict):
                norm = {str(k).strip().upper(): float(v) for k, v in row.items() if isinstance(v, (int, float))}
                if norm:
                    out[str(cart_fam).strip().upper()] = norm
        if out:
            return out
    return _FAMILY_COMPLEMENT_MATRIX


def _family_complement_weight(cart_family: str, candidate_family: str) -> float:
    # Keep relevance deterministic and transparent: same-family gets highest weight.
    row = _family_complement_matrix().get(str(cart_family or "UNK").upper(), {})
    if not row:
        return 0.0
    return float(row.get(str(candidate_family or "UNK").upper(), 0.0))


def _persona_accessory_boost(persona: str | None, accessory_slug: str | None) -> float:
    persona_key = str(persona or "").strip().lower()
    slug = str(accessory_slug or "").strip().lower()
    if not persona_key or not slug:
        return 0.0
    wanted = _persona_accessory_slugs().get(persona_key) or set()
    if slug in wanted:
        return 1.0
    return 0.0


def _user_family_history(db, uid: str | None, lookback_days: int = 180) -> dict[str, float]:
    """
    Lightweight transaction-history affinity derived from historical carts/orders.
    Returns normalized family weights (0..1).
    """
    user = str(uid or "").strip()
    if not user:
        return {}
    rows = []
    cutoff = (datetime.utcnow() - timedelta(
        days=max(1, int(lookback_days))
    )).isoformat(sep=" ")
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    """
                    SELECT line_items
                    FROM draft_orders
                    WHERE customer_id = :uid
                      AND tenant_id = :tenant
                      AND created_at >= :cutoff
                    ORDER BY created_at DESC
                    LIMIT 150
                    """
                ),
                {"uid": user, "tenant": _ct(), "cutoff": cutoff},
            ).fetchall()
    except Exception as exc:   # observable, not silent (review-9 #7): a dead DB must not read
        logger.warning("upsell affinity history unavailable: %s", repr(exc)[:100])
        rows = []              # as 'no purchase history'
    fam_counts: dict[str, float] = {}
    for r in rows or []:
        raw = r[0] if isinstance(r, (list, tuple)) else None
        if raw is None and hasattr(r, "_mapping"):
            raw = r._mapping.get("line_items")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            data = []
        if not isinstance(data, list):
            continue
        for it in data:
            if not isinstance(it, dict):
                continue
            fam = _sku_family(it.get("sku"))
            qty = max(1, int(it.get("quantity") or 1))
            fam_counts[fam] = fam_counts.get(fam, 0.0) + float(qty)
    if not fam_counts:
        return {}
    mx = max(float(v) for v in fam_counts.values())
    if mx <= 0:
        return {}
    return {k: round(float(v) / mx, 4) for k, v in fam_counts.items()}


def ensure_recommend_interactions_table(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommend_interactions (
                    id TEXT PRIMARY KEY,
                    event_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    consent_state TEXT NOT NULL DEFAULT 'unknown',
                    uid_hash TEXT,
                    sku TEXT,
                    action TEXT,
                    surface TEXT,
                    trace_id TEXT,
                    context_json TEXT
                )
                """
            )
        )
    except Exception:
        pass


def _safe_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            if isinstance(val, dict):
                return val
        except Exception:
            return {}
    return {}


def _draft_order_lines(db, since_days: int = 90) -> list[list[dict]]:
    rows = []
    cutoff = (datetime.utcnow() - timedelta(
        days=max(1, int(since_days))
    )).isoformat(sep=" ")
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    """
                    SELECT line_items
                    FROM draft_orders
                    WHERE tenant_id = :tenant
                      AND created_at >= :cutoff
                    """
                ),
                {"tenant": _ct(), "cutoff": cutoff},
            ).fetchall()
    except Exception as exc:   # observable, not silent (review-9 #7)
        logger.warning("upsell co-occurrence window unavailable: %s", repr(exc)[:100])
        return []
    out: list[list[dict]] = []
    for r in rows or []:
        raw = r[0] if isinstance(r, (list, tuple)) else None
        if raw is None and hasattr(r, "_mapping"):
            raw = r._mapping.get("line_items")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or [])
            if isinstance(data, list):
                out.append(data)
        except Exception:
            continue
    if out:
        return out
    # CSV fallback for demo mode.
    csv_path = os.getenv("RECEIPT_ITEMS_CSV", "data/demo/jan_feb_2026/receipt_items_2months.csv")
    try:
        grouped: dict[str, list[dict]] = {}
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = str(row.get("receipt_id") or "").strip()
                sku = str(row.get("sku") or "").strip()
                if not rid or not sku:
                    continue
                qty = int(float(row.get("qty") or 1))
                grouped.setdefault(rid, []).append({"sku": sku, "quantity": max(1, qty)})
        return list(grouped.values())
    except Exception:
        return []


def _product_catalog(db) -> list[dict]:
    rows = []
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    """
                    SELECT p.sku, p.name, p.price_cents, p.specs, COALESCE(i.stock, 0) AS stock
                    FROM products p
                    LEFT JOIN inventory i ON i.product_id = p.id
                    WHERE COALESCE(p.active, 1) = 1
                    """
                )
            ).fetchall()
    except Exception:
        try:
            with db.begin_nested():
                rows = db.execute(
                    text(
                        """
                        SELECT p.sku, p.name, p.price_cents, p.specs, COALESCE(i.stock, 0) AS stock
                        FROM products p
                        LEFT JOIN inventory i ON i.product_id = p.id
                        """
                    )
                ).fetchall()
        except Exception:
            rows = []
    out = []
    for r in rows or []:
        sku = r[0] if isinstance(r, (list, tuple)) else None
        name = r[1] if isinstance(r, (list, tuple)) else None
        price_cents = r[2] if isinstance(r, (list, tuple)) else None
        specs = r[3] if isinstance(r, (list, tuple)) else None
        stock = r[4] if isinstance(r, (list, tuple)) else 0
        if not sku:
            continue
        out.append(
            {
                "sku": str(sku),
                "name": str(name or sku),
                "price_cents": int(price_cents or 0),
                "stock": int(stock or 0),
                "specs": _safe_json(specs),
            }
        )
    if out:
        return out
    # Fallback to the same source used by /ui/products.json so checkout upsell
    # does not go empty when request-bound DB sessions point at sparse catalogs.
    try:
        from src.app.routers.ui_storefront import _get_products as _ui_get_products
        ui_products = _ui_get_products() or []
        mapped: list[dict] = []
        for p in ui_products:
            if not isinstance(p, dict):
                continue
            sku = str(p.get("sku") or "").strip()
            if not sku:
                continue
            price = p.get("price")
            try:
                price_cents = int(float(price) * 100) if price is not None else int(p.get("price_cents") or 0)
            except Exception:
                price_cents = int(p.get("price_cents") or 0)
            mapped.append(
                {
                    "sku": sku,
                    "name": str(p.get("name") or sku),
                    "price_cents": int(price_cents or 0),
                    "stock": int(p.get("stock") or 0),
                    "specs": _safe_json(p.get("specs")),
                }
            )
        if mapped:
            return mapped
    except Exception:
        pass
    return []


def _interaction_stats(db, lookback_days: int = 30) -> dict[str, dict[str, int]]:
    rows = []
    cutoff = (datetime.utcnow() - timedelta(
        days=max(1, int(lookback_days))
    )).isoformat(sep=" ")
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    """
                    SELECT sku, action, COUNT(*) as n
                    FROM recommend_interactions
                    WHERE event_time >= :cutoff
                    GROUP BY sku, action
                    """
                ),
                {"cutoff": cutoff},
            ).fetchall()
    except Exception:
        return {}
    out: dict[str, dict[str, int]] = {}
    for r in rows or []:
        sku = str(r[0] or "")
        act = str(r[1] or "").lower()
        n = int(r[2] or 0)
        if not sku:
            continue
        out.setdefault(sku, {})
        out[sku][act] = out[sku].get(act, 0) + n
    if out:
        return out
    # CSV fallback for demo mode when DB table has no interaction telemetry yet.
    csv_path = os.getenv("RECOMMEND_INTERACTIONS_CSV", "data/demo/jan_feb_2026/recommend_interactions_2months.csv")
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sku = str(row.get("sku") or "").strip()
                act = str(row.get("event_type") or "").strip().lower()
                if not sku or not act:
                    continue
                out.setdefault(sku, {})
                out[sku][act] = out[sku].get(act, 0) + 1
    except Exception:
        pass
    return out


def _copurchase_scores(lines: list[list[dict]], cart_skus: set[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for order in lines:
        skus = {str(it.get("sku") or "").strip() for it in order if isinstance(it, dict)}
        skus = {s for s in skus if s}
        if not skus or not (skus & cart_skus):
            continue
        overlap = len(skus & cart_skus)
        for s in (skus - cart_skus):
            scores[s] = scores.get(s, 0.0) + (1.0 + 0.2 * overlap)
    return scores


def _sales_window_counts(lines: list[list[dict]], recent_cutoff_orders: int = 60) -> tuple[dict[str, int], dict[str, int]]:
    # No reliable order timestamp in draft lines payload; use recency by insertion order as approximation.
    recent = lines[-max(1, int(recent_cutoff_orders)) :]
    prior = lines[:-max(1, int(recent_cutoff_orders))]
    recent_counts: dict[str, int] = {}
    prior_counts: dict[str, int] = {}
    for bucket, target in ((recent, recent_counts), (prior, prior_counts)):
        for order in bucket:
            for it in order:
                if not isinstance(it, dict):
                    continue
                sku = str(it.get("sku") or "").strip()
                if not sku:
                    continue
                qty = int(it.get("quantity") or 1)
                target[sku] = target.get(sku, 0) + max(1, qty)
    return recent_counts, prior_counts


def _looks_poisoned(name: str, sku: str, factors: dict[str, float], interactions: dict[str, int], sales_qty: int) -> tuple[bool, str | None]:
    if _SUSPICIOUS_NAME_PAT.search(name or "") or _SUSPICIOUS_NAME_PAT.search(sku or ""):
        return True, "prompt_injection_pattern"
    hovers = int(interactions.get("hover", 0))
    clicks = int(interactions.get("click", 0))
    ctr = float(clicks) / float(max(1, hovers))
    if hovers >= 30 and ctr >= 0.95 and sales_qty == 0:
        return True, "interaction_poisoning_ctr_spike"
    if factors.get("trend", 0.0) > 2.5 and factors.get("co_purchase", 0.0) <= 0.1 and sales_qty <= 1:
        return True, "untrusted_trend_spike"
    return False, None


def _stock_confidence(stock: int, recent_sales_qty: int) -> float:
    # Confidence is high when stock comfortably covers recent demand.
    st = max(0, int(stock or 0))
    demand = max(1, int(recent_sales_qty or 0))
    ratio = float(st) / float(demand)
    if ratio >= 3.0:
        return 0.95
    if ratio >= 1.5:
        return 0.8
    if ratio >= 1.0:
        return 0.65
    if ratio >= 0.5:
        return 0.4
    return 0.2


def _lifecycle_profile(db, uid_hash: str | None) -> dict[str, Any]:
    if not uid_hash:
        return {"segment": "unknown", "orders": 0, "ltv_cents": 0}
    orders = 0
    ltv_cents = 0
    try:
        rows = db.execute(
            text(
                """
                SELECT o.total_cents
                FROM order_sessions s
                JOIN orders o ON o.id = s.order_id
                WHERE s.uid = :uid
                """
            ),
            {"uid": uid_hash},
        ).fetchall()
        for r in rows or []:
            orders += 1
            ltv_cents += int((r[0] if isinstance(r, (list, tuple)) else 0) or 0)
    except Exception:
        return {"segment": "unknown", "orders": 0, "ltv_cents": 0}
    seg = "new_user" if orders <= 1 else "repeat_user"
    if ltv_cents >= 300000:
        seg = "high_ltv"
    return {"segment": seg, "orders": orders, "ltv_cents": ltv_cents}


_UPSELL_REASON_LABELS: dict[str, str] = {
    "bundle_affinity": "Often purchased with similar carts",
    "frequently_bought_together": "Popular companion item",
    "margin_guardrail": "Good value-to-price tradeoff",
    "low_return_risk": "Reliable pick with low return risk",
    "inventory_pressure": "Stock position favors this option",
    "cart_family_fit": "Complements items already in your cart",
    "query_intent_fit": "Matches your latest shopping goal",
    "persona_fit": "Fits your shopper profile",
    "history_affinity": "Consistent with your past purchases",
}

_UPSELL_REASON_BASE_WEIGHTS: dict[str, float] = {
    "bundle_affinity": 0.34,
    "frequently_bought_together": 0.28,
    "margin_guardrail": 0.16,
    "low_return_risk": 0.12,
    "inventory_pressure": 0.10,
    "cart_family_fit": 0.24,
    "query_intent_fit": 0.20,
    "persona_fit": 0.16,
    "history_affinity": 0.14,
}


def _safe_ratio(numerator: float, denominator: float) -> float:
    d = float(denominator or 0.0)
    if d <= 0.0:
        return 0.0
    return float(numerator or 0.0) / d


def _bounded01(value: float) -> float:
    v = float(value or 0.0)
    return max(0.0, min(1.0, v))


def _estimate_return_risk(interactions_for_sku: dict[str, int]) -> float:
    refunds = float(interactions_for_sku.get("refund", 0) + interactions_for_sku.get("return", 0))
    accepts = float(
        interactions_for_sku.get("add_to_cart", 0)
        + interactions_for_sku.get("atc", 0)
        + interactions_for_sku.get("cart_add", 0)
    )
    views = float(interactions_for_sku.get("view", 0) + interactions_for_sku.get("click", 0))
    base = _safe_ratio(refunds + 1.0, accepts + views + 4.0)
    return _bounded01(base)


def _estimate_margin_guardrail(price_cents: int) -> float:
    # We use a conservative synthetic margin proxy until true COGS joins are wired.
    price = max(0, int(price_cents or 0))
    if price <= 0:
        return 0.0
    if price < 1500:
        return 0.74
    if price < 5000:
        return 0.66
    if price < 20000:
        return 0.58
    return 0.46


def _build_reason_code_breakdown(
    *,
    co_purchase: float,
    trend: float,
    margin_guardrail: float,
    low_return_risk: float,
    stock_confidence: float,
    cart_family_fit: float = 0.0,
    query_intent_fit: float = 0.0,
    persona_fit: float = 0.0,
    history_affinity: float = 0.0,
) -> list[dict[str, Any]]:
    signal_strength = {
        "bundle_affinity": _bounded01(co_purchase / 3.0),
        "frequently_bought_together": _bounded01((co_purchase / 2.5) * 0.7 + ((trend - 1.0) / 1.2) * 0.3),
        "margin_guardrail": _bounded01(margin_guardrail),
        "low_return_risk": _bounded01(low_return_risk),
        "inventory_pressure": _bounded01(1.0 - stock_confidence),
        "cart_family_fit": _bounded01(cart_family_fit),
        "query_intent_fit": _bounded01(query_intent_fit),
        "persona_fit": _bounded01(persona_fit),
        "history_affinity": _bounded01(history_affinity),
    }
    breakdown = []
    for code, base_weight in _UPSELL_REASON_BASE_WEIGHTS.items():
        conf = _bounded01(signal_strength.get(code, 0.0))
        weighted = round(base_weight * conf, 4)
        breakdown.append(
            {
                "code": code,
                "label": _UPSELL_REASON_LABELS.get(code, code.replace("_", " ")),
                "weight": round(base_weight, 4),
                "confidence": round(conf, 4),
                "weighted_score": weighted,
            }
        )
    breakdown.sort(key=lambda item: float(item.get("weighted_score") or 0.0), reverse=True)
    return breakdown


def _train_and_score_conversion_model(
    *,
    candidates: list[dict[str, Any]],
    interactions: dict[str, dict[str, int]],
) -> tuple[dict[str, float], str]:
    if not candidates:
        return ({}, "none")
    rows: list[tuple[list[float], float, str]] = []
    for c in candidates:
        sku = str(c.get("sku") or "")
        if not sku:
            continue
        ints = interactions.get(sku, {})
        pos = float(ints.get("add_to_cart", 0) + ints.get("atc", 0) + ints.get("cart_add", 0) + ints.get("click", 0))
        neg = float(ints.get("view", 0) + ints.get("hover", 0) + ints.get("dismiss", 0))
        target = _bounded01((pos + 1.0) / (pos + neg + 2.0))
        x = [
            float(c.get("co_purchase") or 0.0),
            float(c.get("trend") or 0.0),
            float(c.get("intent") or 0.0),
            float(c.get("affordability") or 0.0),
            float(c.get("stock_confidence") or 0.0),
            float(c.get("lifecycle_boost") or 0.0),
            float(c.get("margin_guardrail") or 0.0),
            float(c.get("low_return_risk") or 0.0),
            float(c.get("inventory_pressure") or 0.0),
        ]
        rows.append((x, target, sku))
    if len(rows) < 6:
        # Not enough supervised signal yet; fallback to weighted heuristics.
        return ({sku: float(t) for _, t, sku in rows}, "heuristic_bootstrap")
    try:
        import lightgbm as lgb  # type: ignore
    except Exception:
        return ({sku: float(t) for _, t, sku in rows}, "heuristic_no_lightgbm")
    try:
        x_train = [x for x, _, _ in rows]
        y_train = [y for _, y, _ in rows]
        train = lgb.Dataset(x_train, label=y_train)
        params = {
            "objective": "regression",
            "metric": "l2",
            "learning_rate": 0.08,
            "num_leaves": 24,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "verbosity": -1,
        }
        model = lgb.train(params, train, num_boost_round=40)
        preds = model.predict(x_train)
        out: dict[str, float] = {}
        for (_, _, sku), pred in zip(rows, preds):
            out[sku] = _bounded01(float(pred))
        return (out, "lightgbm_conversion_v1")
    except Exception:
        return ({sku: float(t) for _, t, sku in rows}, "heuristic_training_fallback")


def recommend_checkout_upsell(
    db,
    *,
    cart_skus: list[str],
    limit: int = 3,
    uid_hash: str | None = None,
    use_case: str | None = None,
    query: str | None = None,
    persona: str | None = None,
    trace_id: str | None = None,
) -> list[dict]:
    clean_cart = [str(s).strip() for s in (cart_skus or []) if str(s).strip()]
    cart_set = set(clean_cart)
    if not cart_set:
        return []

    # Load use-case accessory affinities (pure config lookup, no I/O risk)
    affinity_slugs: list[str] = []
    try:
        from src.app.services.use_case_advisor import get_accessory_affinities
        affinity_slugs = get_accessory_affinities(use_case)
    except Exception:
        affinity_slugs = []
    affinity_set = set(affinity_slugs)

    products = _product_catalog(db)
    if not products:
        return []
    by_sku = {p["sku"]: p for p in products}
    order_lines = _draft_order_lines(db, since_days=120)
    copurchase = _copurchase_scores(order_lines, cart_set)
    recent_sales, prior_sales = _sales_window_counts(order_lines, recent_cutoff_orders=80)
    interactions = _interaction_stats(db, lookback_days=30)
    lifecycle = _lifecycle_profile(db, uid_hash)
    user_history = _user_family_history(db, uid_hash, lookback_days=180)
    cart_families = {_sku_family(s) for s in cart_set if s}
    intent_family = _infer_intent_family(query=query, persona=persona, use_case=use_case)
    # If a laptop is already in cart and we have other families in stock, suppress
    # same-family laptop upsells and prioritize complementary add-ons.
    accessory_like_families = set(ACCESSORY_FAMILIES)
    non_lap_available = any(
        _sku_family(str(p.get("sku") or "")) in accessory_like_families and int(p.get("stock") or 0) > 0
        for p in products
    )
    allowed_candidate_families: set[str] | None = None
    if "LAP" in cart_families:
        # For laptop checkouts, only show true accessories if available.
        # If no accessory families exist, return empty suggestions instead of irrelevant items.
        allowed_candidate_families = set(accessory_like_families) if non_lap_available else set()

    cart_price = sum(int((by_sku.get(s) or {}).get("price_cents") or 0) for s in cart_set)
    feature_rows: list[dict[str, Any]] = []
    candidates: list[UpsellCandidate] = []
    poison_hits: list[dict[str, Any]] = []  # B3: surfaced to the SOC after the loop
    for p in products:
        sku = p["sku"]
        if sku in cart_set:
            continue
        if int(p.get("stock") or 0) <= 0:
            continue
        price = int(p.get("price_cents") or 0)
        # Adaptive price guard (cents): strict for substantial carts, relaxed for low-value ones.
        if not _passes_price_guard(price, cart_price):
            continue
        name = str(p.get("name") or sku)
        specs_dict = p.get("specs") or {}
        if isinstance(specs_dict, str):
            try:
                specs_dict = json.loads(specs_dict)
            except Exception:
                specs_dict = {}
        cand_family = infer_product_family(sku=sku, name=name, specs=specs_dict)
        if allowed_candidate_families is not None and cand_family not in allowed_candidate_families:
            continue
        accessory_slug = infer_accessory_slug(sku=sku, name=name, specs=specs_dict)
        co = float(copurchase.get(sku, 0.0))
        recent = int(recent_sales.get(sku, 0))
        prior = int(prior_sales.get(sku, 0))
        trend = (recent + 1.0) / (prior + 1.0)
        ints = interactions.get(sku, {})
        clicks = float(ints.get("click", 0))
        hovers = float(ints.get("hover", 0))
        intent = clicks * 0.35 + hovers * 0.08
        affordability = 1.0 if cart_price <= 0 else max(0.0, 1.0 - (price / float(max(1, cart_price))))
        stock_conf = _stock_confidence(int(p.get("stock") or 0), recent)
        margin_guardrail = _estimate_margin_guardrail(price)
        return_risk = _estimate_return_risk(ints)
        low_return_risk = _bounded01(1.0 - return_risk)
        inventory_pressure = _bounded01(1.0 - stock_conf)
        lifecycle_boost = 0.0
        if lifecycle.get("segment") == "new_user":
            lifecycle_boost = 0.25 if affordability >= 0.5 else 0.0
        elif lifecycle.get("segment") == "repeat_user":
            lifecycle_boost = 0.2 if co >= 1.5 else 0.0
        elif lifecycle.get("segment") == "high_ltv":
            lifecycle_boost = 0.22 if trend >= 1.1 else 0.0
        # Affinity boost: use-case accessories match gives a small positive nudge
        affinity_boost = 0.0
        if affinity_set:
            cat_tags = product_tags(sku=sku, name=name, specs=specs_dict)
            if accessory_slug:
                cat_tags.add(accessory_slug)
            if cat_tags & affinity_set:
                # Raise affinity_boost to 1.0 so accessories can compete with
                # same-family laptop re-recommendations in the total score.
                affinity_boost = 1.0
        cart_family_fit = 0.0
        if cart_families:
            cart_family_fit = max(_family_complement_weight(cf, cand_family) for cf in cart_families)
        # Suppress query_intent_fit when cart already owns the inferred primary family:
        # a student who has a laptop in the cart wants accessories, not another laptop.
        if intent_family and cand_family == intent_family:
            query_intent_fit = 0.0 if cand_family in cart_families else 1.0
        else:
            query_intent_fit = 0.0
        persona_fit = 0.0
        persona_slug_boost = _persona_accessory_boost(persona, accessory_slug)
        persona_key = str(persona or "").strip().lower()
        if persona_key:
            if persona_key in {"student", "gamer", "office", "corporate", "engineer", "creator"}:
                if "LAP" in cart_families:
                    # Cart already has a laptop; persona_fit should now reward
                    # use-case accessories (mouse, headset, bag, etc.) instead.
                    persona_fit = max(1.0 if affinity_boost > 0 else 0.0, persona_slug_boost)
                else:
                    persona_fit = 1.0 if cand_family == "LAP" else 0.0
            elif persona_key in {"fashion", "apparel"}:
                persona_fit = 1.0 if cand_family == "FSH" else 0.0
            elif persona_key in {"home", "homeowner"}:
                persona_fit = 1.0 if cand_family == "HMW" else 0.0
        history_affinity = float(user_history.get(cand_family, 0.0))
        score = (
            co * 2.2
            + trend * 0.9
            + intent * 0.35
            + affordability * 0.8
            + stock_conf * 0.6
            + lifecycle_boost
            + affinity_boost
            + cart_family_fit * 2.4
            + query_intent_fit * 1.8
            + persona_fit * 1.4
            + persona_slug_boost * 1.8
            + history_affinity * 1.1
        )
        factors = {
            "co_purchase": round(co, 4),
            "trend": round(trend, 4),
            "intent": round(intent, 4),
            "affordability": round(affordability, 4),
            "stock_confidence": round(stock_conf, 4),
            "lifecycle_boost": round(lifecycle_boost, 4),
            "affinity_boost": round(affinity_boost, 4),
            "margin_guardrail": round(margin_guardrail, 4),
            "low_return_risk": round(low_return_risk, 4),
            "inventory_pressure": round(inventory_pressure, 4),
            "cart_family_fit": round(cart_family_fit, 4),
            "query_intent_fit": round(query_intent_fit, 4),
            "persona_fit": round(persona_fit, 4),
            "persona_slug_boost": round(persona_slug_boost, 4),
            "history_affinity": round(history_affinity, 4),
        }
        poisoned, poison_reason = _looks_poisoned(name, sku, factors, ints, recent)
        if poisoned:
            poison_hits.append({"sku": sku, "reason": poison_reason or "unknown"})
            continue
        feature_rows.append(
            {
                "sku": sku,
                "co_purchase": co,
                "trend": trend,
                "intent": intent,
                "affordability": affordability,
                "stock_confidence": stock_conf,
                "lifecycle_boost": lifecycle_boost,
                "margin_guardrail": margin_guardrail,
                "low_return_risk": low_return_risk,
                "inventory_pressure": inventory_pressure,
            }
        )

        tags: list[str] = []
        reasons: list[str] = []
        if co >= 2:
            tags.append("bought_together")
            reasons.append("Frequently purchased with current cart items")
        if trend >= 1.35:
            tags.append("trend_rising")
            reasons.append("Recent sales trend is rising")
        if clicks >= 3:
            tags.append("high_click_intent")
            reasons.append("High checkout click-through in recent sessions")
        if affordability >= 0.5:
            tags.append("budget_fit")
            reasons.append("Price fits this cart value band")
        if stock_conf >= 0.75:
            tags.append("stock_confident")
            reasons.append("Inventory coverage is stable for current demand")
        if affinity_boost > 0.0:
            tags.append("use_case_affinity")
            reasons.append("Matches recommended accessories for your use-case")
        if cart_family_fit >= 0.8:
            tags.append("cart_family_fit")
            reasons.append("Matches your current cart category")
        if query_intent_fit >= 0.8:
            tags.append("query_intent_fit")
            reasons.append("Matches your latest query intent")
        if persona_fit >= 0.8:
            tags.append("persona_fit")
            reasons.append("Aligned with your current buyer persona")
        if persona_slug_boost >= 0.8:
            tags.append("persona_bundle_fit")
            reasons.append("Strong accessory fit for this persona and cart")
        if history_affinity >= 0.5:
            tags.append("history_affinity")
            reasons.append("Aligned with your recent transaction history")
        if lifecycle.get("segment") == "new_user" and affordability >= 0.5:
            tags.append("lifecycle_new_user_fit")
            reasons.append("Priced for first-time buyer conversion")
        elif lifecycle.get("segment") == "repeat_user" and co >= 1.5:
            tags.append("lifecycle_repeat_user_bundle")
            reasons.append("Aligned with repeat-buyer basket patterns")
        elif lifecycle.get("segment") == "high_ltv" and trend >= 1.1:
            tags.append("lifecycle_high_ltv_trend")
            reasons.append("High-LTV segment affinity and demand trend")
        if not tags:
            tags.append("catalog_match")
            reasons.append("Relevant based on category and demand history")
        if poison_reason:
            tags.append("poison_guard")
            reasons.append(f"Poison guard activated: {poison_reason}")
        reason_codes = _build_reason_code_breakdown(
            co_purchase=co,
            trend=trend,
            margin_guardrail=margin_guardrail,
            low_return_risk=low_return_risk,
            stock_confidence=stock_conf,
            cart_family_fit=cart_family_fit,
            query_intent_fit=query_intent_fit,
            persona_fit=persona_fit,
            history_affinity=history_affinity,
        )
        confidence = round(sum(float(x.get("confidence") or 0.0) for x in reason_codes[:3]) / 3.0, 4)

        candidates.append(
            UpsellCandidate(
                sku=sku,
                name=name,
                price_cents=price,
                stock=int(p.get("stock") or 0),
                score=round(score, 4),
                tags=tags[:4],
                reasons=reasons[:4],
                factors=factors,
                reason_codes=reason_codes[:5],
                confidence=confidence,
                model_source="rules_heuristic",
            )
        )

    # B3: surface poisoned upsell signals to the SOC. Per-call guards EMIT; the observer
    # correlates aggregate velocity. external_analytical evidence (co-purchase/interactions)
    # filtered here must be visible, not silently dropped.
    if poison_hits and trace_id:
        try:
            from src.app.services.decision_log import log_trace_event
            log_trace_event(
                trace_id, "commerce_integrity", "agent", "Upsell_Poison_Guard", "sku", None,
                {
                    "signal": "upsell_signal_poisoning",
                    "blocked": len(poison_hits),
                    "detections": poison_hits[:20],
                    "surface": "checkout_upsell",
                },
            )
        except Exception:
            pass

    conversion_scores, model_source = _train_and_score_conversion_model(candidates=feature_rows, interactions=interactions)
    rescored: list[UpsellCandidate] = []
    for c in candidates:
        conv = float(conversion_scores.get(c.sku, 0.0))
        # Rule-first hard constraints already filtered candidates; model only reorders survivors.
        final = (c.score * 0.72) + (conv * 2.1)
        rescored.append(
            UpsellCandidate(
                sku=c.sku,
                name=c.name,
                price_cents=c.price_cents,
                stock=c.stock,
                score=round(final, 4),
                tags=c.tags,
                reasons=c.reasons,
                factors={**c.factors, "conversion_model_score": round(conv, 4)},
                reason_codes=c.reason_codes,
                confidence=c.confidence,
                model_source=model_source,
            )
        )

    ranked = sorted(rescored, key=lambda c: c.score, reverse=True)[: max(1, int(limit))]
    if not ranked:
        # Deterministic catalog fallback: keep checkout UX actionable even when
        # interaction/affinity signals are sparse.
        fallback_rows: list[dict[str, Any]] = []
        # Multi-pass price guard:
        # 1) Prefer true add-on band (<=45% cart value)
        # 2) If empty, widen to <=100%
        # 3) If still empty, widen to <=130% to avoid dead-end UX
        if cart_price > 0:
            price_caps = [int(max(25_00, int(cart_price * 0.45))), int(max(30_00, int(cart_price * 1.0))), int(max(35_00, int(cart_price * 1.3)))]
        else:
            price_caps = [60_00, 90_00]
        max_price = price_caps[0]
        for p in products:
            sku = str(p.get("sku") or "").strip()
            if not sku or sku in cart_set:
                continue
            cand_family = _sku_family(sku)
            if allowed_candidate_families is not None and cand_family not in allowed_candidate_families:
                continue
            stock = int(p.get("stock") or 0)
            if stock <= 0:
                continue
            price = int(p.get("price_cents") or 0)
            if price <= 0 or price > max_price:
                continue
            fallback_rows.append(p)
        if not fallback_rows:
            for max_price in price_caps[1:]:
                widened: list[dict[str, Any]] = []
                for p in products:
                    sku = str(p.get("sku") or "").strip()
                    if not sku or sku in cart_set:
                        continue
                    cand_family = _sku_family(sku)
                    if allowed_candidate_families is not None and cand_family not in allowed_candidate_families:
                        continue
                    stock = int(p.get("stock") or 0)
                    if stock <= 0:
                        continue
                    price = int(p.get("price_cents") or 0)
                    if price <= 0 or price > max_price:
                        continue
                    widened.append(p)
                if widened:
                    fallback_rows = widened
                    break
        fallback_rows = sorted(
            fallback_rows,
            key=lambda x: (
                abs(int(x.get("price_cents") or 0) - int(max(20_00, cart_price * 0.25 if cart_price > 0 else 40_00))),
                -int(x.get("stock") or 0),
            ),
        )[: max(1, int(limit))]
        if fallback_rows:
            return [
                {
                    "sku": str(p.get("sku") or ""),
                    "name": str(p.get("name") or p.get("sku") or ""),
                    "price_cents": int(p.get("price_cents") or 0),
                    "stock": int(p.get("stock") or 0),
                    "score": 0.1,
                    "tags": ["fallback_catalog_complement"],
                    "reasons": ["Popular low-cost complement from in-stock catalog"],
                    "factors": {"fallback": True, "price_guard_max_cents": int(max_price)},
                    "reason_codes": [{"code": "fallback_catalog_complement", "confidence": 0.62}],
                    "reason_confidence": 0.62,
                    "model_source": "deterministic_fallback",
                    "lifecycle_segment": lifecycle.get("segment"),
                }
                for p in fallback_rows
            ]
    return [
        {
            "sku": c.sku,
            "name": c.name,
            "price_cents": c.price_cents,
            "stock": c.stock,
            "score": c.score,
            "tags": c.tags,
            "reasons": c.reasons,
            "factors": c.factors,
            "reason_codes": c.reason_codes,
            "reason_confidence": c.confidence,
            "model_source": c.model_source,
            "lifecycle_segment": lifecycle.get("segment"),
        }
        for c in ranked
    ]


def upsell_performance_snapshot(db, *, hours: int = 24, top_k: int = 5) -> dict[str, Any]:
    ensure_recommend_interactions_table(db)
    since = (datetime.utcnow() - timedelta(hours=max(1, int(hours)))).isoformat()

    interactions_by_sku: dict[str, dict[str, int]] = {}
    impressions = 0
    clicks = 0
    add_to_cart = 0
    recent_trace_ids: list[str] = []

    try:
        rows = db.execute(
            text(
                """
                SELECT sku, action, trace_id
                FROM recommend_interactions
                WHERE event_time >= :since AND surface = :surface
                """
            ),
            {"since": since, "surface": "checkout_upsell"},
        ).fetchall()
    except Exception:
        rows = []

    for r in rows or []:
        sku = str(r[0] or "").strip()
        action = str(r[1] or "").strip().lower()
        trace_id = str(r[2] or "").strip()
        if not sku or not action:
            continue
        interactions_by_sku.setdefault(sku, {})
        interactions_by_sku[sku][action] = interactions_by_sku[sku].get(action, 0) + 1
        if action in {"view", "impression"}:
            impressions += 1
        elif action == "click":
            clicks += 1
        elif action in {"add_to_cart", "atc", "cart_add"}:
            add_to_cart += 1
        if trace_id and len(recent_trace_ids) < 12:
            recent_trace_ids.append(trace_id)

    ctr = (float(clicks) / float(max(1, impressions))) if impressions > 0 else 0.0
    add_to_cart_rate = (float(add_to_cart) / float(max(1, clicks))) if clicks > 0 else 0.0

    top_skus: list[dict[str, Any]] = []
    for sku, acts in interactions_by_sku.items():
        sku_views = int(acts.get("view", 0) + acts.get("impression", 0))
        sku_clicks = int(acts.get("click", 0))
        sku_atc = int(acts.get("add_to_cart", 0) + acts.get("atc", 0) + acts.get("cart_add", 0))
        sku_ctr = float(sku_clicks) / float(max(1, sku_views)) if sku_views > 0 else 0.0
        top_skus.append(
            {
                "sku": sku,
                "views": sku_views,
                "clicks": sku_clicks,
                "add_to_cart": sku_atc,
                "ctr": round(sku_ctr, 4),
            }
        )
    top_skus = sorted(top_skus, key=lambda x: (x["ctr"], x["clicks"]), reverse=True)[: max(1, int(top_k))]

    blocked_poisoned = 0
    poison_reasons: dict[str, int] = {}
    try:
        products = _product_catalog(db)
        order_lines = _draft_order_lines(db, since_days=90)
        recent_sales, prior_sales = _sales_window_counts(order_lines, recent_cutoff_orders=80)
        interaction_stats = _interaction_stats(db, lookback_days=30)
        for p in products:
            sku = str(p.get("sku") or "")
            name = str(p.get("name") or sku)
            ints = interaction_stats.get(sku, {})
            recent = int(recent_sales.get(sku, 0))
            prior = int(prior_sales.get(sku, 0))
            trend = (recent + 1.0) / (prior + 1.0)
            factors = {"co_purchase": 0.0, "trend": round(trend, 4)}
            poisoned, reason = _looks_poisoned(name, sku, factors, ints, recent)
            if poisoned:
                blocked_poisoned += 1
                poison_reasons[reason or "unknown"] = poison_reasons.get(reason or "unknown", 0) + 1
    except Exception:
        pass

    return {
        "window_hours": int(hours),
        "impressions": impressions,
        "clicks": clicks,
        "add_to_cart": add_to_cart,
        "ctr": round(ctr, 4),
        "add_to_cart_rate": round(add_to_cart_rate, 4),
        "blocked_poisoned_candidates": int(blocked_poisoned),
        "poison_reason_counts": poison_reasons,
        "top_skus": top_skus,
        "sample_trace_ids": recent_trace_ids[:6],
    }
