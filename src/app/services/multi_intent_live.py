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
import os
import re
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text as _sql

from src.app.models.db import db_session
from src.app.services.intent_decomposer import decompose_turn

# Genuine amendment cues for the empty-cart fallback gate. Deliberately EXCLUDES the ambiguous
# "i need"/"i want" that intent_decomposer._AMEND_RE carries — those also fit a FRESH search ("I need
# 25 laptops"), which must NOT bind a prior shortlist. Verb + strong-lexical cues only.
_FALLBACK_AMEND_CUE_RE = re.compile(
    r"\b(?:instead|actually|make\s+it|change\s+(?:it|that|to)|rather|nah|scratch\s+that|"
    r"on\s+second\s+thought|reduce|lower|drop|cut|bump|bring\s+it|down\s+to|halve|double|"
    r"swap|switch|replace)\b", re.I)  # swap/replace bind to the just-shown shortlist (2026-07-09)
from src.app.services.multi_intent_planner import plan_turn
from src.app.services.scatter_gather_guard import _matches_category
from src.app.platform.tenant_context import current_tenant_id as _ct  # R10.2


def _row_to_result(sku: str, name: str, price_cents: Any, specs: Any,
                   col_category: Any = None, col_type: Any = None) -> Dict[str, Any]:
    """Shape one products row into the opaque result the planner + guard expect
    ({name, price_cents, price, category, type, tags}). ``specs`` may arrive as a dict (pg jsonb) or a
    JSON string (sqlite) — normalise both. Category/type resolve from the DEDICATED products columns first
    (the agnostic keystone: products.category / products.product_type), falling back to the specs JSON, so a
    catalog that populates the columns instead of specs still matches scoped new-line scatter."""
    cat = str(col_category or "").strip()
    typ = str(col_type or "").strip()
    tags: List[str] = []
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except (ValueError, TypeError):
            specs = {}
    if isinstance(specs, dict):
        cat = cat or str(specs.get("category") or specs.get("product_type") or "")
        typ = typ or str(specs.get("type") or specs.get("product_type") or "")
        raw_tags = specs.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags if str(t).strip()]
    cents = int(price_cents or 0)
    return {"sku": str(sku), "name": str(name or ""), "price_cents": cents,
            "price": round(cents / 100.0, 2), "category": cat, "type": typ, "tags": tags}


def _load_catalog(db) -> List[Dict[str, Any]]:
    """One read of the active catalog as opaque rows for in-memory category/budget filtering. Reads the
    dedicated category/product_type columns when the schema has them, falling back to a specs-only SELECT
    for schemas that don't (rollback between attempts so a pg aborted-tx doesn't poison the fallback)."""
    for select, with_cols in (
        ("SELECT sku, name, price_cents, specs, category, product_type FROM products WHERE active = :active", True),
        ("SELECT sku, name, price_cents, specs FROM products WHERE active = :active", False),
    ):
        try:
            rows = db.execute(_sql(select), {"active": True}).fetchall()
            if with_cols:
                return [_row_to_result(r[0], r[1], r[2], r[3], col_category=r[4], col_type=r[5]) for r in rows]
            return [_row_to_result(r[0], r[1], r[2], r[3]) for r in rows]
        except Exception:
            try:
                db.rollback()   # a missing-column SELECT aborts a pg tx; clear it before the fallback
            except Exception:
                pass
    return []


def _prior_lines_from_cart(db, uid: str, by_sku: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The buyer's active draft cart → prior_lines the planner carries forward (newest last). Each line binds
    its category from the catalog snapshot so the guard's context-survival + category checks have real data.
    Empty when there is no draft cart (a fresh single-intent turn — planner then adds nothing)."""
    row = db.execute(
        _sql("SELECT line_items FROM draft_orders WHERE customer_id = :uid AND tenant_id = :t "
             "AND status = 'draft' ORDER BY created_at DESC LIMIT 1"),
        {"uid": str(uid), "t": _ct()},
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
        try:
            qty = int(it.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1   # a corrupt/non-numeric cart quantity must not abort the whole plan (mislabeled as a DB fail)
        lines.append({
            "ref": sku,
            "category": prod.get("category") or prod.get("type") or "",
            "requested_qty": qty,
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

    # Cart empty → fall back to the recent shortlist's top pick so an amendment still has a target —
    # but ONLY when the query is genuinely AMENDMENT-shaped ("actually make it 15 instead"). A FRESH
    # search ("what laptops for work? I need about 25") has no amendment cue: binding a prior shortlist
    # there makes the decomposer read "need 25" as an amendment and surface a spurious MultiIntentCard
    # on a plain new search (the demo regression). No cue → no fallback → fresh search stays fresh.
    if not prior and fallback_prior_skus and _FALLBACK_AMEND_CUE_RE.search(str(query or "")):
        for sku in fallback_prior_skus:
            prod = by_sku.get(str(sku))
            if prod:
                prior = [{"ref": prod["sku"], "category": prod.get("category") or prod.get("type") or "",
                          "requested_qty": 1, "name": prod.get("name") or prod["sku"]}]
                break

    # Gate: only engage on a genuinely multi-intent turn (an amendment OR a new category line). A plain
    # single-intent search gains nothing from the planner, so we return None and leave the turn untouched.
    # Hybrid parse: the deterministic fast-path first, then the schema-constrained LLM binding (flag-gated)
    # for phrasings the regex misses ("reduce to 10 and get 40 mice"). Decompose ONCE here and reuse it in
    # plan_turn so the model is called at most once per turn.
    llm_fn = _binding_llm_fn()
    # prior context (numbers + an opaque label only) makes RELATIVE language computable for the LLM tier:
    # "halve the order" is unanswerable without the prior qty (20 → 10). The deterministic validator
    # re-checks whatever the model emits, so the context can inform but never bypass the grammar rules.
    prior_ctx = None
    if prior:
        _last = prior[-1]
        prior_ctx = {"qty": _last.get("requested_qty"), "name": _last.get("name"),
                     # ALL cart lines (name + qty), so the model can bind NAMED refs ("get rid of the HP
                     # Envy") to the right line in a multi-product cart — not just the last one.
                     "lines": [{"qty": p.get("requested_qty"), "name": p.get("name")} for p in prior[-6:]]}
    probe = decompose_turn(query, has_prior_selection=bool(prior), llm_fn=llm_fn, prior_context=prior_ctx)
    if not probe.amendments and not probe.new_lines:
        return None

    planned = plan_turn(query, prior_lines=prior, search_fn=_make_search_fn(catalog, limit),
                        intents=probe, llm_fn=llm_fn)
    if planned and probe.amendments:
        # Presentation metadata only: commerce authority still comes from the
        # parsed numeric operation plus buyer confirmation. Approximate language
        # must not look like an already-authorized exact cart quantity.
        planned["quantity_expression"] = (
            "approximate"
            if re.search(r"\b(?:about|around|roughly|approximately|circa)\b|~\s*\d", query, re.I)
            else "exact"
        )
    return planned


def _binding_llm_fn() -> Optional[Callable[[str], str]]:
    """A sync, schema-forced Ollama call for the multi-intent LLM binding — or None when disabled. Flag-gated
    (MULTI_INTENT_LLM_BINDING_ENABLED, default OFF) so the default path stays deterministic + Ollama-free.
    Best-effort: any error returns '' so the deterministic parse always stands."""
    if str(os.getenv("MULTI_INTENT_LLM_BINDING_ENABLED", "")).strip().lower() not in ("1", "true", "yes", "on"):
        return None
    model = (os.getenv("MULTI_INTENT_LLM_MODEL") or os.getenv("OLLAMA_SMALL_MODEL")
             or os.getenv("OLLAMA_DEFAULT_MODEL") or "qwen3:14b")
    timeout = float(os.getenv("MULTI_INTENT_LLM_TIMEOUT_SEC", "12") or 12)

    def _fn(prompt: str) -> str:
        try:
            from src.app.services.local_model_roles import configured_digest, execute_local_model_role

            return execute_local_model_role(
                prompt, role="multi_intent_binder", purpose="multi_intent_binding",
                prompt_id="multi-intent-binder", model=model,
                digest=configured_digest(
                    "MULTI_INTENT_LLM_MODEL_DIGEST", "OLLAMA_SMALL_MODEL_DIGEST",
                    "OLLAMA_DEFAULT_MODEL_DIGEST",
                ),
                timeout_s=timeout, max_output_tokens=512,
            )
        except Exception:
            return ""   # deterministic parse stands
    return _fn
