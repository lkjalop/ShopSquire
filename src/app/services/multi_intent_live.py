"""Live-flow adapter for the P0 multi-intent planner (edge adapter — NOT agnostic CORE).

Bridges the pure, vertical-blind ``multi_intent_planner.plan_turn`` into the live chat flow:

  1. reads the buyer's PRIOR selection (their active draft cart) → the ``prior_lines`` the planner amends
     ("actually make it 15" refers to the chosen laptop already in the cart);
  2. builds a catalog ``search_fn`` over the products table (category-token + scoped budget) for the NEW
     lines ("what headsets and hard drives for $1200 for those");
  3. returns the planner's verdict + plan, additively, so the chat response can render a confirmation card.

Deliberately kept OUT of ``_CORE_MODULES``: the planner / guard / decomposer are pure and vertical-blind and
live in core; THIS module is the edge adapter that knows about carts, the products table, and category tokens.
It reuses the guard's own ``_matches_category`` so the catalog filter and the adversarial recheck agree on
what "belongs to a category". One DB read per turn (the small seed catalog); the search_fn then filters that
in-memory snapshot — no DB access inside the injected closure (keeps it off the request's DB session).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text as _sql

from src.app.models.db import db_session
from src.app.services.intent_decomposer import decompose_turn
from src.app.services.multi_intent_planner import plan_turn
from src.app.services.scatter_gather_guard import _matches_category


def _row_to_result(sku: str, name: str, price_cents: Any, specs: Any) -> Dict[str, Any]:
    """Shape one products row into the opaque result the planner + guard expect
    ({name, price_cents, price, category, type, tags}). ``specs`` may arrive as a dict (pg jsonb) or a
    JSON string (sqlite) — normalise both. Category/type/tags come from specs (the agnostic keystone)."""
    cat = typ = ""
    tags: List[str] = []
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except (ValueError, TypeError):
            specs = {}
    if isinstance(specs, dict):
        cat = str(specs.get("category") or specs.get("product_type") or "")
        typ = str(specs.get("type") or specs.get("product_type") or "")
        raw_tags = specs.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags if str(t).strip()]
    cents = int(price_cents or 0)
    return {"sku": str(sku), "name": str(name or ""), "price_cents": cents,
            "price": round(cents / 100.0, 2), "category": cat, "type": typ, "tags": tags}


def _load_catalog(db) -> List[Dict[str, Any]]:
    """One read of the active catalog as opaque rows for in-memory category/budget filtering.
    Bound param for ``active`` so the literal adapts across sqlite (1) and postgres (true)."""
    rows = db.execute(
        _sql("SELECT sku, name, price_cents, specs FROM products WHERE active = :active"),
        {"active": True},
    ).fetchall()
    return [_row_to_result(r[0], r[1], r[2], r[3]) for r in rows]


def _prior_lines_from_cart(db, uid: str, by_sku: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The buyer's active draft cart → prior_lines the planner carries forward (newest last). Each line binds
    its category from the catalog snapshot so the guard's context-survival + category checks have real data.
    Empty when there is no draft cart (a fresh single-intent turn — planner then adds nothing)."""
    row = db.execute(
        _sql("SELECT line_items FROM draft_orders WHERE customer_id = :uid AND status = 'draft' "
             "ORDER BY created_at DESC LIMIT 1"),
        {"uid": str(uid)},
    ).fetchone()
    if not row:
        return []
    raw = row[0]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = []
    items = raw if isinstance(raw, list) else []
    lines: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("sku"):
            continue
        sku = str(it.get("sku"))
        prod = by_sku.get(sku) or {}
        lines.append({
            "ref": sku,
            "category": prod.get("category") or prod.get("type") or "",
            "requested_qty": int(it.get("quantity") or 1),
            "name": prod.get("name") or sku,
        })
    return lines


def _make_search_fn(catalog: List[Dict[str, Any]], limit: int) -> Callable[[str, Optional[int]], List[Dict[str, Any]]]:
    """Closure over the in-memory catalog snapshot: match a NEW line's category token (guard's own matcher)
    and keep only picks within the scoped budget, cheapest first. No DB inside — safe to call from plan_turn."""
    def _search(category: str, budget_max: Optional[int]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in catalog:
            if not _matches_category(r, category):
                continue
            if budget_max and r["price"] > float(budget_max) + 0.001:
                continue
            out.append(r)
        out.sort(key=lambda x: x["price"])
        return out[:limit]
    return _search


def plan_live(query: str, uid: str, *, limit: int = 6,
              fallback_prior_skus: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Run the planner against the buyer's live context. Returns None for a plain single-intent turn (no
    amendment and no new line) so the caller adds no noise; otherwise returns
    {intents, plan, verdict, needs_confirmation, objection_angle, warnings} (JSON-safe). Never raises —
    surfaces a load failure as a warning inside the result rather than crashing the turn.

    ``fallback_prior_skus``: the buyer's most-recent shortlist (top pick first), captured BEFORE this turn.
    When the cart is empty (e.g. add-to-cart 409'd on stock) an amendment like "actually 15 instead" would
    have nothing to bind to; we then bind "__last__" to the first catalog-resolvable fallback sku so the
    amendment still lands on the item the buyer was just shown."""
    try:
        with db_session() as db:
            catalog = _load_catalog(db)
            by_sku = {r["sku"]: r for r in catalog}
            prior = _prior_lines_from_cart(db, uid, by_sku)
    except Exception as exc:  # DB/catalog read failed — visible, non-silent, and non-fatal to the turn
        return {"intents": {}, "plan": [], "verdict": {"ok": False, "violations": ["catalog_unavailable"]},
                "needs_confirmation": True, "objection_angle": None,
                "warnings": [f"multi_intent catalog load failed: {str(exc)[:120]}"]}

    # Cart empty → fall back to the recent shortlist's top pick so an amendment still has a target.
    if not prior and fallback_prior_skus:
        for sku in fallback_prior_skus:
            prod = by_sku.get(str(sku))
            if prod:
                prior = [{"ref": prod["sku"], "category": prod.get("category") or prod.get("type") or "",
                          "requested_qty": 1, "name": prod.get("name") or prod["sku"]}]
                break

    # Gate: only engage on a genuinely multi-intent turn (an amendment OR a new category line). A plain
    # single-intent search gains nothing from the planner, so we return None and leave the turn untouched.
    probe = decompose_turn(query, has_prior_selection=bool(prior))
    if not probe.amendments and not probe.new_lines:
        return None

    return plan_turn(query, prior_lines=prior, search_fn=_make_search_fn(catalog, limit))
