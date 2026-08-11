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
        # PostgreSQL and other production databases are migration-owned. Runtime
        # DDL here created lock/race risk and could poison the transaction when a
        # compatibility ALTER failed. Keep the bootstrap only for ephemeral
        # SQLite tests that intentionally do not run Alembic.
        dialect = str(
            getattr(
                getattr(getattr(db, "bind", None), "dialect", None),
                "name",
                "",
            )
        )
        if dialect != "sqlite":
            return
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
                cart_version INTEGER NOT NULL DEFAULT 0,
                result      TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at  TEXT,
                applied_at  TEXT
            )"""))
        # Additive compatibility for old local SQLite files only.
        try:
            db.execute(text("ALTER TABLE cart_mutation_plans ADD COLUMN cart_version INTEGER NOT NULL DEFAULT 0"))
        except Exception as _alter_exc:   # already present (idempotent) — observable, not silent
            logger.debug("cart_version column add skipped (present?): %s", repr(_alter_exc)[:80])
        # indexes (parity with the 20260712_cart_mutation_plans migration — P0.4)
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_cmp_owner_status ON cart_mutation_plans(tenant_id, uid, status)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_cmp_expires ON cart_mutation_plans(expires_at)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_cmp_trace ON cart_mutation_plans(trace_id)"))
        db.commit()


_TERMINAL_STATUSES = (
    "applied", "already_applied", "stale_cart", "expired", "rejected", "superseded", "error",
)


def cleanup_plans(*, older_than_days: int = 7) -> int:
    """Retention (review-6 #6): delete TERMINAL plans older than the window (also redacts the
    stored `query`). Returns the row count deleted. Run from a periodic job / worker tick."""
    _ensure_plans_table()
    cutoff = (_now() - timedelta(days=max(0, int(older_than_days)))).strftime(_TS_FMT)
    ph = ", ".join(f"'{s}'" for s in _TERMINAL_STATUSES)
    with db_session() as db:
        res = db.execute(text(
            f"DELETE FROM cart_mutation_plans WHERE status IN ({ph}) "
            "AND COALESCE(applied_at, created_at) < :cut"), {"cut": cutoff})
        db.commit()
        return int(getattr(res, "rowcount", 0) or 0)


def propose_plan(*, tenant_id: str, uid: str, plan: CartMutationPlan,
                 cart_items: List[Dict[str, Any]], query: str = "",
                 trace_id: Optional[str] = None) -> Dict[str, Any]:
    """Persist a resolved plan against the cart state it was resolved on. Returns
    {plan_id, risk, cart_hash, expires_at}. Never mutates a cart."""
    _ensure_plans_table()
    plan_id = f"cmp-{uuid.uuid4().hex[:16]}"
    risk = risk_tier(plan)
    # Read the ACTUAL persisted cart's version + hash (the same source apply reads) — the
    # version is the atomic CAS token (P0.2); the hash is a redundant, human-legible guard.
    from src.app.routers.cart import _load_cart_row
    cart_version = 0
    try:
        with db_session() as rdb:
            _, real_items, cart_version = _load_cart_row(rdb, uid, tenant_id=tenant_id)
        cart_hash = cart_content_hash(real_items)
    except Exception as exc:
        logger.debug("propose real-cart read fell back to passed slice: %s", repr(exc)[:80])
        cart_hash = cart_content_hash(cart_items)
    expires_at = (_now() + timedelta(minutes=_PLAN_TTL_MINUTES)).strftime(_TS_FMT)
    superseded_plan_ids: List[str] = []
    with db_session() as db:
        # One owner has one current confirmation decision. A newer proposal explicitly
        # supersedes every still-unconfirmed proposal so an old chat card cannot be applied
        # after the buyer has revised the instruction. The update and insert commit together.
        superseded_plan_ids = [str(row[0]) for row in db.execute(text(
            "SELECT id FROM cart_mutation_plans "
            "WHERE tenant_id = :t AND uid = :u AND status = 'proposed' "
            "ORDER BY created_at DESC"
        ), {"t": str(tenant_id or "default"), "u": str(uid or "")}).fetchall()[:20]]
        if superseded_plan_ids:
            db.execute(text(
                "UPDATE cart_mutation_plans SET status = 'superseded', result = :result, "
                "applied_at = :at WHERE tenant_id = :t AND uid = :u AND status = 'proposed'"
            ), {
                "result": json.dumps({"reason": "replaced_by_newer_plan", "superseded_by": plan_id}),
                "at": _now().strftime(_TS_FMT),
                "t": str(tenant_id or "default"),
                "u": str(uid or ""),
            })
        db.execute(text(
            "INSERT INTO cart_mutation_plans (id, tenant_id, uid, trace_id, query, plan, risk, "
            "status, cart_hash, cart_version, expires_at) VALUES (:id, :t, :u, :tr, :q, :p, :r, "
            "'proposed', :h, :cv, :e)"),
            {"id": plan_id, "t": str(tenant_id or "default"), "u": str(uid or ""),
             "tr": trace_id, "q": str(query or "")[:400], "p": json.dumps(plan.as_dict()),
             "r": risk, "h": cart_hash, "cv": int(cart_version), "e": expires_at})
        db.commit()
    return {"plan_id": plan_id, "risk": risk, "cart_hash": cart_hash,
            "cart_version": cart_version, "expires_at": expires_at,
            "superseded_plan_ids": superseded_plan_ids}


def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    _ensure_plans_table()
    with db_session() as db:
        row = db.execute(text(
            "SELECT id, tenant_id, uid, trace_id, query, plan, risk, status, cart_hash, result, "
            "expires_at, applied_at, cart_version FROM cart_mutation_plans WHERE id = :id"),
            {"id": str(plan_id or "")}).fetchone()
    if not row:
        return None
    return {"plan_id": row[0], "tenant_id": row[1], "uid": row[2], "trace_id": row[3],
            "query": row[4], "plan": json.loads(row[5]) if row[5] else {}, "risk": row[6],
            "status": row[7], "cart_hash": row[8],
            "result": json.loads(row[9]) if row[9] else None,
            "expires_at": row[10], "applied_at": row[11], "cart_version": int(row[12] or 0)}


def reject_plan(plan_id: str, *, tenant_id: str, uid: str) -> Dict[str, Any]:
    """Durably discard an unconfirmed plan without touching the cart."""
    row = get_plan(plan_id)
    if row is None:
        return {"status": "not_found", "plan_id": plan_id}
    if row["tenant_id"] != str(tenant_id or "default") or row["uid"] != str(uid or ""):
        return {"status": "forbidden", "plan_id": plan_id}
    if row["status"] == "rejected":
        return {"status": "already_rejected", "plan_id": plan_id}
    if row["status"] != "proposed":
        return {"status": "conflict", "plan_id": plan_id, "current_status": row["status"]}
    with db_session() as db:
        changed = db.execute(text(
            "UPDATE cart_mutation_plans SET status = 'rejected', result = :result, "
            "applied_at = :at WHERE id = :id AND tenant_id = :t AND uid = :u "
            "AND status = 'proposed'"
        ), {
            "result": json.dumps({"reason": "buyer_discarded"}),
            "at": _now().strftime(_TS_FMT),
            "id": plan_id,
            "t": str(tenant_id or "default"),
            "u": str(uid or ""),
        })
        db.commit()
    if int(getattr(changed, "rowcount", 0) or 0) == 1:
        return {"status": "rejected", "plan_id": plan_id}
    current = get_plan(plan_id)
    return {
        "status": "conflict",
        "plan_id": plan_id,
        "current_status": (current or {}).get("status"),
    }


def _finish(plan_id: str, status: str, result: Dict[str, Any], *, db=None) -> None:
    """Mark a plan terminal. With `db` (the transactional path) it runs on the caller's session
    and does NOT commit — the caller's single commit is the atomic unit. Without it, own session."""
    stmt = text("UPDATE cart_mutation_plans SET status = :s, result = :r, applied_at = :a "
                "WHERE id = :id")
    params = {"s": status, "r": json.dumps(result), "a": _now().strftime(_TS_FMT), "id": plan_id}
    if db is not None:
        db.execute(stmt, params)
        return
    with db_session() as own:
        own.execute(stmt, params)
        own.commit()


def _affordability_resolution(
    *,
    plan: CartMutationPlan,
    working: List[Dict[str, Any]],
    by_sku: Dict[str, Any],
    cap_cents: int,
    proposed_total_cents: int,
) -> Optional[Dict[str, Any]]:
    """Build choices only for one explicit quantity change; compound math must be replanned."""
    quantity_ops = [
        op for op in plan.ops
        if op.action == "set_quantity" and len(op.target_skus) == 1 and op.quantity is not None
    ]
    if len(quantity_ops) != 1:
        return None
    op = quantity_ops[0]
    sku = str(op.target_skus[0])
    variant = by_sku.get(sku)
    if variant is None or variant.price_cents is None:
        return None
    unit_cents = int(variant.price_cents)
    requested = int(op.quantity or 0)
    if unit_cents <= 0 or requested <= 0:
        return None
    other_total = sum(
        int(by_sku[str(item["sku"])].price_cents) * int(item.get("quantity") or 0)
        for item in working
        if str(item.get("sku") or "") != sku
    )
    available_for_line = max(0, int(cap_cents) - other_total)
    max_affordable = available_for_line // unit_cents
    cheaper_unit_cap = available_for_line // requested
    return {
        "kind": "total_budget_exceeded",
        "sku": sku,
        "product_name": str(getattr(variant, "title", "") or sku),
        "currency": str(getattr(variant, "currency", "") or ""),
        "requested_quantity": requested,
        "max_affordable_quantity": max_affordable,
        "current_unit_price_cents": unit_cents,
        "cheaper_unit_price_max_cents": cheaper_unit_cap,
        "budget_max_cents": int(cap_cents),
        "proposed_total_cents": int(proposed_total_cents),
        "other_lines_total_cents": other_total,
        "choices": ["reduce_quantity", "increase_budget", "choose_cheaper_product"],
        "requires_confirmation": True,
    }


_CARRIED_AGE_HOURS = 1.0   # mirrors cart-age labelling: a line idle >1h reads as carried


def _carried_skus(items: List[Dict[str, Any]]) -> Optional[List[str]]:
    """SERVER-authoritative carried set (C2): a line whose per-line added_at is older than the
    carried threshold belongs to an earlier session — the same truth the cart-age label uses,
    no frontend snapshot needed. Returns None when NO line carries a parseable added_at (old
    carts) — the caller must refuse rather than guess (never guess-then-wipe)."""
    any_stamp = False
    carried: List[str] = []
    cutoff = _now() - timedelta(hours=_CARRIED_AGE_HOURS)
    for it in (items or []):
        raw = str(it.get("added_at") or "")
        if not raw:
            continue
        try:
            stamp = datetime.strptime(raw[:19], _TS_FMT)
        except ValueError as exc:
            logger.debug("unparseable added_at on line %s: %s", it.get("sku"), repr(exc)[:60])
            continue
        any_stamp = True
        if stamp < cutoff and it.get("sku"):
            carried.append(str(it["sku"]))
    return carried if any_stamp else None


def _stash_undo(redis, uid: str, items: List[Dict[str, Any]]) -> None:
    """Snapshot the pre-mutation cart to the SAME key /undo restores from (review-5 gap: an NL
    clear was un-undoable while the button path stashed). Best-effort."""
    if redis is None or not items:
        return
    try:
        from src.app.routers.cart import _undo_key, _undo_ttl
        redis.setex(_undo_key(uid), _undo_ttl(),
                    json.dumps({"items": [dict(it) for it in items],
                                "restore_mode": "replace", "saved_at": _now().strftime(_TS_FMT)}))
    except Exception as exc:
        logger.debug("undo stash skipped: %s", repr(exc)[:100])


def apply_plan(plan_id: str, *, tenant_id: str, uid: str, redis=None) -> Dict[str, Any]:
    """Execute a proposed plan — the ONLY mutation path. Returns a dict whose `status` is one of:
    applied | already_applied | rejected | stale_cart | expired | not_found | forbidden |
    conflict | error. Never raises; never partially applies (P0.2: ONE atomic transaction).

    Atomicity (review-6 #2/#3/#4): the status-claim CAS, the cart read, the versioned cart
    write, and the plan-complete all run in ONE db_session and commit ONCE. Any raise before that
    commit rolls the WHOLE thing back — status stays 'proposed', cart unchanged, plan retryable
    (no wedge, no mutate-then-lie). Concurrency: the status CAS's row lock serializes concurrent
    applies; the cart's version CAS serializes any concurrent writer (stepper / second plan) —
    a writer that lands mid-apply bumps the version, our versioned UPDATE gets rowcount 0, and we
    return stale_cart having written nothing (the lost-write is impossible, not just narrowed)."""
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

    from src.app.routers.cart import (
        _batch_stock_levels,
        _hydrate,
        _load_cart_row,
        _save_cart_versioned,
        apply_quantity_line,
    )
    plan = CartMutationPlan.from_dict(row["plan"])
    proposed_version = int(row.get("cart_version") or 0)
    # stock is ADVISORY — read outside the write transaction so the txn stays single-connection.
    set_skus = [op.target_skus[0] for op in plan.ops
                if op.action == "set_quantity" and op.target_skus]
    set_skus.extend(op.replacement_sku for op in plan.ops
                    if op.action == "replace_item" and op.replacement_sku)
    stock_map = _batch_stock_levels(set_skus) if set_skus else {}
    prior_items: List[Dict[str, Any]] = []
    working: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []

    try:
        with db_session() as db:
            # 1. IDEMPOTENCY CLAIM — the row lock serializes concurrent applies (uncommitted here).
            claimed = db.execute(text(
                "UPDATE cart_mutation_plans SET status = 'applying' "
                "WHERE id = :id AND status = 'proposed'"), {"id": plan_id})
            if getattr(claimed, "rowcount", 0) == 0:
                cur = db.execute(text("SELECT status, result FROM cart_mutation_plans WHERE id = :id"),
                                 {"id": plan_id}).fetchone()
                st = cur[0] if cur else None
                if st == "applied":
                    res = json.loads(cur[1]) if cur and cur[1] else {}
                    return {"status": "already_applied", "plan_id": plan_id, **res}
                return {"status": "conflict", "plan_id": plan_id, "current_status": st}

            # 2. READ the cart in the SAME txn; stale if the version moved since propose.
            # tenant from the PLAN row (verified above) — the audited authority (R10.2).
            cart_id, items, version = _load_cart_row(db, uid, tenant_id=tenant_id)
            if cart_id is None or version != proposed_version:
                _finish(plan_id, "stale_cart", {"reason": "cart_changed_since_proposal"}, db=db)
                db.commit()
                return {"status": "stale_cart", "plan_id": plan_id}

            prior_items = [dict(it) for it in items]
            working = [dict(it) for it in items]

            # 3. ALL-OR-NOTHING op validation into the in-memory working copy; the first failure
            # commits the 'rejected' status and returns with the cart untouched (nothing saved).
            for op in plan.ops:
                if op.action == "clear_all":
                    working = []
                    applied.append({"action": "clear_all"})
                elif op.action == "remove_items":
                    missing = [s for s in op.target_skus
                               if not any(it.get("sku") == s for it in working)]
                    if missing:
                        _finish(plan_id, "rejected", {"error": "target_not_in_cart", "skus": missing}, db=db)
                        db.commit()
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
                        allow_sourcing=bool(op.allow_sourcing))
                    if err is not None:
                        _finish(plan_id, "rejected", {"error": err}, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id, "error": err}
                    entry: Dict[str, Any] = {"action": "set_quantity", "sku": sku, "quantity": op.quantity}
                    if shortfall:
                        entry["sourcing"] = shortfall
                    applied.append(entry)
                elif op.action == "replace_item":
                    source_sku = op.target_skus[0] if op.target_skus else ""
                    replacement_sku = str(op.replacement_sku or "")
                    if not source_sku or not replacement_sku:
                        _finish(plan_id, "rejected", {"error": "invalid_replacement"}, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id,
                                "error": {"error": "invalid_replacement"}}
                    if not any(it.get("sku") == source_sku for it in working):
                        error = {"error": "target_not_in_cart", "skus": [source_sku]}
                        _finish(plan_id, "rejected", error, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id, "error": error}
                    from src.app.services.catalog_read_model import get_variant
                    replacement = get_variant(db, replacement_sku, tenant_id=tenant_id)
                    if replacement is None or not replacement.active or replacement.price_cents is None:
                        error = {"error": "replacement_unavailable", "sku": replacement_sku}
                        _finish(plan_id, "rejected", error, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id, "error": error}
                    qty = int(op.quantity or 0)
                    if (op.unit_price_cents is not None
                            and int(replacement.price_cents) != int(op.unit_price_cents)):
                        error = {"error": "replacement_price_changed", "sku": replacement_sku,
                                 "proposed_unit_price_cents": int(op.unit_price_cents),
                                 "current_unit_price_cents": int(replacement.price_cents)}
                        _finish(plan_id, "rejected", error, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id, "error": error}
                    if (op.budget_max_cents is not None
                            and int(replacement.price_cents) * qty > int(op.budget_max_cents)):
                        error = {"error": "replacement_price_changed", "sku": replacement_sku,
                                 "unit_price_cents": int(replacement.price_cents),
                                 "budget_max_cents": int(op.budget_max_cents)}
                        _finish(plan_id, "rejected", error, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id, "error": error}
                    without_source = [it for it in working if it.get("sku") != source_sku]
                    working, shortfall, err = apply_quantity_line(
                        without_source, replacement_sku, qty, stock_map.get(replacement_sku, 0),
                        allow_sourcing=True)
                    if err is not None:
                        _finish(plan_id, "rejected", {"error": err}, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id, "error": err}
                    entry = {"action": "replace_item", "sku": source_sku,
                             "replacement_sku": replacement_sku, "quantity": qty}
                    if shortfall:
                        entry["sourcing"] = shortfall
                    applied.append(entry)
                elif op.action == "clear_previous":
                    carried = _carried_skus(working)
                    if carried is None:
                        _finish(plan_id, "rejected", {"error": "carried_set_unknown"}, db=db)
                        db.commit()
                        return {"status": "rejected", "plan_id": plan_id,
                                "error": {"error": "carried_set_unknown"}}
                    working = [it for it in working if it.get("sku") not in set(carried)]
                    applied.append({"action": "clear_previous", "skus": carried})
                else:
                    _finish(plan_id, "rejected", {"error": "unsupported_action", "action": op.action}, db=db)
                    db.commit()
                    return {"status": "rejected", "plan_id": plan_id,
                            "error": {"error": "unsupported_action", "action": op.action}}

            # 4. VERSIONED CAS WRITE — succeeds only if no concurrent writer bumped the version
            # during our op loop; rowcount 0 → stale, nothing written.
            # Re-authorize any carried whole-order budget against current catalog prices
            # inside the transaction. Session memory proposes the cap; current data decides.
            budget_caps = [
                int(op.budget_max_cents) for op in plan.ops
                if op.budget_max_cents is not None
            ]
            if budget_caps:
                cap = min(budget_caps)
                from src.app.services.catalog_read_model import get_variants
                final_skus = [str(item.get("sku") or "") for item in working if item.get("sku")]
                variants = get_variants(db, final_skus, tenant_id=tenant_id)
                by_sku = {variant.sku: variant for variant in variants}
                missing_prices = [
                    sku for sku in final_skus
                    if sku not in by_sku or by_sku[sku].price_cents is None
                ]
                if missing_prices:
                    error = {"error": "total_budget_unverifiable", "skus": missing_prices}
                    _finish(plan_id, "rejected", error, db=db)
                    db.commit()
                    return {"status": "rejected", "plan_id": plan_id, "error": error}
                for op in plan.ops:
                    if (op.action == "set_quantity" and op.target_skus
                            and op.unit_price_cents is not None):
                        current_price = int(by_sku[op.target_skus[0]].price_cents)
                        if current_price != int(op.unit_price_cents):
                            error = {
                                "error": "cart_line_price_changed",
                                "sku": op.target_skus[0],
                                "proposed_unit_price_cents": int(op.unit_price_cents),
                                "current_unit_price_cents": current_price,
                            }
                            _finish(plan_id, "rejected", error, db=db)
                            db.commit()
                            return {"status": "rejected", "plan_id": plan_id, "error": error}
                proposed_total = sum(
                    int(by_sku[str(item["sku"])].price_cents) * int(item.get("quantity") or 0)
                    for item in working
                )
                if proposed_total > cap:
                    error = {
                        "error": "total_budget_exceeded",
                        "budget_max_cents": cap,
                        "proposed_total_cents": proposed_total,
                    }
                    resolution = _affordability_resolution(
                        plan=plan,
                        working=working,
                        by_sku=by_sku,
                        cap_cents=cap,
                        proposed_total_cents=proposed_total,
                    )
                    if resolution is not None:
                        error["resolution"] = resolution
                    _finish(plan_id, "rejected", error, db=db)
                    db.commit()
                    return {"status": "rejected", "plan_id": plan_id, "error": error}

            if not _save_cart_versioned(db, cart_id, working, version):
                _finish(plan_id, "stale_cart", {"reason": "cart_changed_during_apply"}, db=db)
                db.commit()
                return {"status": "stale_cart", "plan_id": plan_id}
            # 5. plan-complete + THE single commit: cart write and 'applied' status land together.
            _finish(plan_id, "applied", {"applied": applied}, db=db)
            db.commit()
    except Exception as exc:
        # the transaction rolled back (nothing committed): status still 'proposed', cart
        # unchanged, plan retryable. No wedge, no partial mutation.
        logger.warning("cart apply_plan rolled back (plan=%s): %s", plan_id, repr(exc)[:160])
        return {"status": "error", "plan_id": plan_id}

    # POST-COMMIT (best-effort, cannot affect state): undo snapshot (review-6 #4 — stash only a
    # cart that DID change) + hydrate for the response.
    _stash_undo(redis, uid, prior_items)
    try:
        with db_session() as rdb:
            _, final_items, _ = _load_cart_row(rdb, uid, tenant_id=tenant_id)
        hydrated = _hydrate(final_items)
    except Exception as _he:
        logger.debug("hydrate after apply failed (non-fatal): %s", repr(_he)[:80])
        hydrated = {"items": working}
    return {"status": "applied", "plan_id": plan_id, "applied": applied, "cart": hydrated}
