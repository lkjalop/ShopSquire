from __future__ import annotations

import json
import re
import os
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import text


_SUSPICIOUS_NAME_PAT = re.compile(
    r"(?i)(ignore\s+previous|jailbreak|system\s+prompt|developer\s+mode|override|drop\s+table|<script)"
)


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


def ensure_recommend_interactions_table(db) -> None:
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommend_interactions (
                    id TEXT PRIMARY KEY,
                    event_time TEXT DEFAULT CURRENT_TIMESTAMP,
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
    try:
        rows = db.execute(
            text(
                """
                SELECT line_items
                FROM draft_orders
                WHERE datetime(created_at) >= datetime('now', :window_expr)
                """
            ),
            {"window_expr": f"-{max(1, int(since_days))} days"},
        ).fetchall()
    except Exception:
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
            return []
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
    return out


def _interaction_stats(db, lookback_days: int = 30) -> dict[str, dict[str, int]]:
    rows = []
    try:
        rows = db.execute(
            text(
                """
                SELECT sku, action, COUNT(*) as n
                FROM recommend_interactions
                WHERE datetime(event_time) >= datetime('now', :window_expr)
                GROUP BY sku, action
                """
            ),
            {"window_expr": f"-{max(1, int(lookback_days))} days"},
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


def recommend_checkout_upsell(db, *, cart_skus: list[str], limit: int = 3, uid_hash: str | None = None) -> list[dict]:
    clean_cart = [str(s).strip() for s in (cart_skus or []) if str(s).strip()]
    cart_set = set(clean_cart)
    if not cart_set:
        return []

    products = _product_catalog(db)
    if not products:
        return []
    by_sku = {p["sku"]: p for p in products}
    order_lines = _draft_order_lines(db, since_days=120)
    copurchase = _copurchase_scores(order_lines, cart_set)
    recent_sales, prior_sales = _sales_window_counts(order_lines, recent_cutoff_orders=80)
    interactions = _interaction_stats(db, lookback_days=30)
    lifecycle = _lifecycle_profile(db, uid_hash)

    cart_price = sum(int((by_sku.get(s) or {}).get("price_cents") or 0) for s in cart_set)
    candidates: list[UpsellCandidate] = []
    for p in products:
        sku = p["sku"]
        if sku in cart_set:
            continue
        if int(p.get("stock") or 0) <= 0:
            continue
        price = int(p.get("price_cents") or 0)
        # Keep price guard adaptive: strict for expensive carts, relaxed for low-value carts.
        if cart_price > 1200 and price > int(cart_price * 0.7):
            continue
        if cart_price > 0 and cart_price <= 1200 and price > int(cart_price * 1.9):
            continue
        name = str(p.get("name") or sku)
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
        lifecycle_boost = 0.0
        if lifecycle.get("segment") == "new_user":
            lifecycle_boost = 0.25 if affordability >= 0.5 else 0.0
        elif lifecycle.get("segment") == "repeat_user":
            lifecycle_boost = 0.2 if co >= 1.5 else 0.0
        elif lifecycle.get("segment") == "high_ltv":
            lifecycle_boost = 0.22 if trend >= 1.1 else 0.0
        score = co * 2.2 + trend * 0.9 + intent * 0.35 + affordability * 0.8 + stock_conf * 0.6 + lifecycle_boost
        factors = {
            "co_purchase": round(co, 4),
            "trend": round(trend, 4),
            "intent": round(intent, 4),
            "affordability": round(affordability, 4),
            "stock_confidence": round(stock_conf, 4),
            "lifecycle_boost": round(lifecycle_boost, 4),
        }
        poisoned, poison_reason = _looks_poisoned(name, sku, factors, ints, recent)
        if poisoned:
            continue

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
            )
        )

    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)[: max(1, int(limit))]
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
