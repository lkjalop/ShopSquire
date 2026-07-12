"""Transactional cart-mutation service (V2 cart milestone C1 — GPT-5.6 review-5 #1/#3/#5).

"Model proposes, policy authorizes, human confirms when risky, transactional service
executes." This module is the EXECUTE (and the durable middle):

  propose_plan  — persist a resolved CartMutationPlan against the cart state it was resolved
                  on (content hash = the optimistic-concurrency token) with a risk tier and an
                  expiry. Nothing mutates.
  apply_plan    — the ONLY way a plan touches a cart. Idempotent (a status CAS claims the
                  plan; re-applies return the stored result), stale-guarded (cart changed →
                  refuse), ALL-OR-NOTHING (every op validates in memory against ONE cart
                  read; any failure aborts with nothing saved; success is ONE _save_cart),
                  undo-stashed (destructive applies snapshot the prior cart to the same Redis
                  key the /undo endpoint restores from).

Plans are tenant-keyed from day one (review-5 #4): apply refuses a tenant/uid mismatch even
though today's draft_orders are uid-scoped — new artifacts do not inherit the legacy gap.

The per-line quantity decision is cart.py's apply_quantity_line — imported, never copied
(the duplicated-parser drift class). sqlite/PG portable; table lazily ensured (the voucher
pattern)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.domain.cart_mutation import (
    CartMutationPlan,
    cart_content_hash,
    risk_tier,
)
from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.cart_mutation_service")

_PLAN_TTL_MINUTES = 10
_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _now() -> datetime:
    return datetime.utcnow()


def _ensure_plans_table() -> None:
    with db_session() as db:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS cart_mutation_plans (
                id          TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL,
                uid         TEXT NOT NULL,
                trace_id    TEXT,
                query       TEXT,
                plan        TEXT NOT NULL,
                risk        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'proposed',
                cart_hash   TEXT NOT NULL,
                result      TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at  TEXT,
                applied_at  TEXT
            )"""))
        db.commit()


def propose_plan(*, tenant_id: str, uid: str, plan: CartMutationPlan,
                 cart_items: List[Dict[str, Any]], query: str = "",
                 trace_id: Optional[str] = None) -> Dict[str, Any]:
    """Persist a resolved plan against the cart state it was resolved on. Returns
    {plan_id, risk, cart_hash, expires_at}. Never mutates a cart."""
    _ensure_plans_table()
    plan_id = f"cmp-{uuid.uuid4().hex[:16]}"
    risk = risk_tier(plan)
    cart_hash = cart_content_hash(cart_items)
    expires_at = (_now() + timedelta(minutes=_PLAN_TTL_MINUTES)).strftime(_TS_FMT)
    with db_session() as db:
        db.execute(text(
            "INSERT INTO cart_mutation_plans (id, tenant_id, uid, trace_id, query, plan, risk, "
            "status, cart_hash, expires_at) VALUES (:id, :t, :u, :tr, :q, :p, :r, 'proposed', "
            ":h, :e)"),
            {"id": plan_id, "t": str(tenant_id or "default"), "u": str(uid or ""),
             "tr": trace_id, "q": str(query or "")[:400], "p": json.dumps(plan.as_dict()),
             "r": risk, "h": cart_hash, "e": expires_at})
        db.commit()
    return {"plan_id": plan_id, "risk": risk, "cart_hash": cart_hash, "expires_at": expires_at}


def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    _ensure_plans_table()
    with db_session() as db:
        row = db.execute(text(
            "SELECT id, tenant_id, uid, trace_id, query, plan, risk, status, cart_hash, result, "
            "expires_at, applied_at FROM cart_mutation_plans WHERE id = :id"),
            {"id": str(plan_id or "")}).fetchone()
    if not row:
        return None
    return {"plan_id": row[0], "tenant_id": row[1], "uid": row[2], "trace_id": row[3],
            "query": row[4], "plan": json.loads(row[5]) if row[5] else {}, "risk": row[6],
            "status": row[7], "cart_hash": row[8],
            "result": json.loads(row[9]) if row[9] else None,
            "expires_at": row[10], "applied_at": row[11]}


def _finish(plan_id: str, status: str, result: Dict[str, Any]) -> None:
    with db_session() as db:
        db.execute(text(
            "UPDATE cart_mutation_plans SET status = :s, result = :r, applied_at = :a "
            "WHERE id = :id"),
            {"s": status, "r": json.dumps(result), "a": _now().strftime(_TS_FMT), "id": plan_id})
        db.commit()


def _stash_undo(redis, uid: str, items: List[Dict[str, Any]]) -> None:
    """Snapshot the pre-mutation cart to the SAME key /undo restores from (review-5 gap: an NL
    clear was un-undoable while the button path stashed). Best-effort."""
    if redis is None or not items:
        return
    try:
        from src.app.routers.cart import _undo_key, _undo_ttl
        redis.setex(_undo_key(uid), _undo_ttl(),
                    json.dumps({"items": [{"sku": it.get("sku"), "quantity": it.get("quantity"),
                                           "name": it.get("name")} for it in items]}))
    except Exception as exc:
        logger.debug("undo stash skipped: %s", repr(exc)[:100])


def apply_plan(plan_id: str, *, tenant_id: str, uid: str, redis=None) -> Dict[str, Any]:
    """Execute a proposed plan — the ONLY mutation path. Returns a dict whose `status` is one of:
    applied | already_applied | rejected | stale_cart | expired | not_found | forbidden |
    conflict. Never raises; never partially applies."""
    row = get_plan(plan_id)
    if row is None:
        return {"status": "not_found", "plan_id": plan_id}
    # tenant + uid must BOTH match the proposal (review-5 #4: plans are tenant-keyed artifacts)
    if row["tenant_id"] != str(tenant_id or "default") or row["uid"] != str(uid or ""):
        return {"status": "forbidden", "plan_id": plan_id}
    if row["status"] == "applied":
        return {"status": "already_applied", "plan_id": plan_id, **(row["result"] or {})}
    if row["status"] != "proposed":
        return {"status": "conflict", "plan_id": plan_id, "current_status": row["status"]}
    if row["expires_at"]:
        try:
            if _now() > datetime.strptime(row["expires_at"], _TS_FMT):
                _finish(plan_id, "expired", {"reason": "plan_ttl_elapsed"})
                return {"status": "expired", "plan_id": plan_id}
        except ValueError as exc:
            logger.debug("unparseable expires_at on %s: %s", plan_id, repr(exc)[:80])

    # IDEMPOTENCY CLAIM (CAS on status): exactly one caller wins; a concurrent double-submit
    # (the SSE-abort/retry class, review-5 #6) loses the CAS and reads the stored result.
    with db_session() as db:
        claimed = db.execute(text(
            "UPDATE cart_mutation_plans SET status = 'applying' "
            "WHERE id = :id AND status = 'proposed'"), {"id": plan_id})
        db.commit()
        if getattr(claimed, "rowcount", 0) == 0:
            after = get_plan(plan_id) or {}
            if after.get("status") == "applied":
                return {"status": "already_applied", "plan_id": plan_id, **(after.get("result") or {})}
            return {"status": "conflict", "plan_id": plan_id,
                    "current_status": after.get("status")}

    from src.app.routers.cart import (
        _batch_stock_levels,
        _get_or_create_cart,
        _hydrate,
        _save_cart,
        apply_quantity_line,
    )
    cart_id, items, _ = _get_or_create_cart(uid)
    # STALE GUARD: the plan was proposed against a specific cart state; if a stepper, another
    # tab, or another plan changed it since, refuse — never apply yesterday's plan to today's cart.
    if cart_content_hash(items) != row["cart_hash"]:
        _finish(plan_id, "stale_cart", {"reason": "cart_changed_since_proposal"})
        return {"status": "stale_cart", "plan_id": plan_id}

    plan = CartMutationPlan.from_dict(row["plan"])
    prior_items = [dict(it) for it in items]
    working = [dict(it) for it in items]
    applied: List[Dict[str, Any]] = []
    set_skus = [op.target_skus[0] for op in plan.ops
                if op.action == "set_quantity" and op.target_skus]
    stock_map = _batch_stock_levels(set_skus) if set_skus else {}

    # ALL-OR-NOTHING: every op validates against the in-memory working copy; the FIRST failure
    # aborts the whole plan with nothing saved (review-5 #5 — no partial application, ever).
    for op in plan.ops:
        if op.action == "clear_all":
            working = []
            applied.append({"action": "clear_all"})
        elif op.action == "remove_items":
            missing = [s for s in op.target_skus
                       if not any(it.get("sku") == s for it in working)]
            if missing:
                _finish(plan_id, "rejected", {"error": "target_not_in_cart", "skus": missing})
                return {"status": "rejected", "plan_id": plan_id,
                        "error": {"error": "target_not_in_cart", "skus": missing}}
            working = [it for it in working if it.get("sku") not in set(op.target_skus)]
            applied.append({"action": "remove_items", "skus": list(op.target_skus)})
        elif op.action == "keep_only":
            keep = set(op.target_skus)
            working = [it for it in working if it.get("sku") in keep]
            applied.append({"action": "keep_only", "skus": list(op.target_skus)})
        elif op.action == "set_quantity":
            sku = op.target_skus[0]
            working, shortfall, err = apply_quantity_line(
                working, sku, int(op.quantity or 0), stock_map.get(sku, 0),
                allow_sourcing=False)   # sourcing consent is its own confirm flow (C1 follow-up)
            if err is not None:
                _finish(plan_id, "rejected", {"error": err})
                return {"status": "rejected", "plan_id": plan_id, "error": err}
            entry: Dict[str, Any] = {"action": "set_quantity", "sku": sku, "quantity": op.quantity}
            if shortfall:
                entry["sourcing"] = shortfall
            applied.append(entry)
        else:
            # clear_previous needs the carried set — not executable server-side yet; the whole
            # plan is rejected rather than a guess-wipe (never partial, never guessed).
            _finish(plan_id, "rejected", {"error": "unsupported_action", "action": op.action})
            return {"status": "rejected", "plan_id": plan_id,
                    "error": {"error": "unsupported_action", "action": op.action}}

    _stash_undo(redis, uid, prior_items)
    _save_cart(cart_id, working)          # ONE save = the atomic commit point
    result = {"applied": applied, "cart": _hydrate(working)}
    _finish(plan_id, "applied", {"applied": applied})
    return {"status": "applied", "plan_id": plan_id, **result}
