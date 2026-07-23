"""Recommendation dispatch facade (V2 — GPT-5.6 review-2 finding #1, #4, #6, #10).

THE LIVE DISPATCH BOUNDARY. The first core wiring returned from inside suggest() BEFORE the
shared commerce guard, image security, and normal persistence — a proof-of-life, not a
production boundary. This module is that boundary, built right:

  preflight (SHARED, not duplicated)
    → inspect_commerce_request  — the REAL guard (prompt-injection/XSS/SQLi/uid/sku); a
      'block' verdict emits the security event and returns the same block payload legacy
      does, so the core can never bypass it. Its verdict is passed into the envelope so the
      core reads the real guard, not a second regex (finding #10).
    → session slice             — best-effort read of the durable session (prior node,
      constraints, shortlist, referents); populated now, consumed by prior-subject
      resolution in a later step.
  dispatch (mode ladder, finding #4)
    → off      : return None → legacy serves (default; zero live change).
    → shadow   : legacy serves; a durable job is enqueued for OFFLINE diffing (no inline
                 second brain — that doubles latency, the critique that killed wiring #1).
    → canary:N : stable per-user bucketing → N% to core, rest to legacy.
    → primary  : core serves every CANARY-eligible lane.
  lane gate (finding #6)
    → SEARCH/FILTER/COMPARE/EXPLAIN/OFF_CATALOG are canary-served. Independently gated,
      read-only PROCUREMENT advice and approved POLICY answers can be enrolled without
      widening the search canary. Cart, claims, inventory, and rollback-image turns still
      delegate. (Cost: a non-core lane under canary/primary runs the router then falls
      through — double work on a small traffic slice; safety over latency, documented.)
  postflight
    → the caller's with_trace() runs sanitization + REAL trace persistence (the persisted
      flag is now honest — finding #2).

Returns a finalized payload dict when the core owns the turn, or None to fall through to
legacy. Never raises into the router: any failure records + returns None (legacy is always
a safe fallback).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional

from src.app.security.commerce_request_guard import inspect_commerce_request
from src.app.services.recommendation_core.envelope import TurnEnvelope

logger = logging.getLogger("shopsquire.recommendation_facade")

# Search lanes share one canary ladder. Other safe read-only lanes require their own switches;
# execution authority stays in the mature domain routers. This prevents a policy/procurement
# extraction from silently broadening the recommendation rollout.
CANARY_LANES = frozenset({"SEARCH", "FILTER", "COMPARE", "EXPLAIN", "OFF_CATALOG"})
_SHADOW_QUEUE_KEY = "shadow:core:queue"          # legacy list (fallback + migration drain)
_SHADOW_STREAM_KEY = "shadow:core:stream"        # R10.4b: the durable path
_SHADOW_QUEUE_MAX = 5000
_SHADOW_STREAM_MAX = 10000

FacadeStatus = Literal["served", "delegate", "blocked", "degraded", "error"]


def _lane_is_enrolled(lane: str) -> bool:
    """Keep read-only lane promotion independent from the search canary ladder.

    These switches authorize only bounded responses. Consequential execution remains owned by
    the existing fulfillment/support domain routers.
    """
    if lane in CANARY_LANES:
        return True
    flag = {
        "PROCUREMENT": "RECOMMEND_PROCUREMENT_ADVICE_MODE",
        "POLICY_QUESTION": "RECOMMEND_POLICY_ANSWER_MODE",
        "SUPPORT_CLAIM": "RECOMMEND_SUPPORT_HANDOFF_MODE",
        "INVENTORY": "RECOMMEND_INVENTORY_READ_MODE",
    }.get(lane)
    return bool(
        flag
        and os.getenv(flag, "off").strip().lower() in {"1", "true", "yes", "on"}
    )


@dataclass(frozen=True)
class FacadeOutcome:
    """Typed dispatch result for callers that must distinguish why V2 did not serve."""

    status: FacadeStatus
    payload: Optional[Dict[str, Any]] = None
    reason: str = ""
    lane: Optional[str] = None
    latency_ms: float = 0.0

    @property
    def served(self) -> bool:
        return self.status == "served" and self.payload is not None


def _fallback_metric(reason: str) -> None:
    """Count a core-eligible turn that fell through to legacy. Best-effort (metrics optional)."""
    try:
        from src.app.observability.metrics import record_core_fallback
        record_core_fallback(reason)
    except Exception as exc:   # observable, not silent (no-silent-except ratchet)
        logger.debug("fallback metric skipped: %s", repr(exc)[:80])


def _resolve_mode() -> tuple[str, int]:
    """(mode, canary_pct). RECOMMEND_CORE_MODE = off | shadow | canary:<pct> | primary."""
    raw = str(os.getenv("RECOMMEND_CORE_MODE", "") or "").strip().lower()
    if raw.startswith("canary"):
        pct = 0
        if ":" in raw:
            try:
                pct = max(0, min(100, int(raw.split(":", 1)[1])))
            except ValueError:
                pct = 0
        return "canary", pct
    if raw in ("shadow", "primary", "off"):
        return raw, 0
    return "off", 0


def _in_canary_bucket(key: str, pct: int) -> bool:
    """Stable per-user/tenant bucketing: the same key always lands the same side of the split
    (deterministic across turns — a user doesn't flip between engines mid-session)."""
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    h = int(hashlib.sha256(str(key or "anon").encode("utf-8")).hexdigest(), 16)
    return (h % 100) < pct


def _enqueue_shadow(redis, *, envelope: "TurnEnvelope", cart_only: bool = False) -> None:
    """Durable shadow job (finding #4): legacy serves live; the offline worker/replay drains
    this queue and diffs core vs the recorded/served response. Best-effort; capped so a
    stalled drainer can't grow it unbounded.

    FULL-ENVELOPE jobs (R10.1/P1.1): the job carries envelope.to_dict() — budget, session,
    image flag, cart — so the worker measures the SAME turn production saw (the old
    query-only jobs silently measured budget-less, session-less turns). Top-level
    query/uid/tenant_id/trace_id stay for queue observability + old-worker back-compat.
    pre_gate is deliberately NOT run for shadow (no hot-path guard cost on a non-served
    turn); the worker's core falls back to its thin gate, honestly recorded as such.

    cart_only=True (C0 resolve-only): enqueued solely for cart-plan resolution (the search
    core is not in shadow) so the worker skips the search diff."""
    if redis is None:
        return
    try:
        payload: Dict[str, Any] = {"query": envelope.query, "uid": envelope.uid,
                                   "tenant_id": envelope.tenant_id,
                                   "trace_id": envelope.trace_id,
                                   "envelope": envelope.to_dict()}
        if envelope.cart:
            payload["cart"] = list(envelope.cart)
            if cart_only:
                payload["cart_only"] = True
        raw = json.dumps(payload)
        # R10.4b DURABLE PATH: a Stream entry survives a worker crash mid-job (consumer-group
        # pending + XAUTOCLAIM recovery). NO MAXLEN on the active input stream (review-9-followup
        # #1: approximate MAXLEN can trim entries still in the group's pending list — un-processed
        # work would be lost, contradicting zero-loss). The worker XDELs each entry AFTER a
        # durable outcome, so the stream stays self-cleaning (length ≈ live backlog); XLEN is the
        # backpressure signal the soak watches. List fallback (with its cap) is for stream-less
        # clients (DummyRedis) only — that cap is acceptable because the list path is best-effort.
        try:
            redis.xadd(_SHADOW_STREAM_KEY, {"payload": raw})
            return
        except (AttributeError, TypeError) as exc:
            logger.debug("no stream support (%s) → legacy list", type(exc).__name__)
        except Exception as exc:
            logger.debug("shadow xadd failed (%s) — falling back to list", repr(exc)[:80])
        redis.lpush(_SHADOW_QUEUE_KEY, raw)
        redis.ltrim(_SHADOW_QUEUE_KEY, 0, _SHADOW_QUEUE_MAX - 1)
    except Exception as exc:
        logger.debug("shadow enqueue skipped: %s", repr(exc)[:100])


def _cart_mode() -> str:
    """RECOMMEND_CART_SERVE = off (default) | shadow | on — the cart lane's OWN ladder,
    independent of the search-core mode (GPT-5.6 review-5, answer #1):
      off    — zero change; the frontend regex serves cart edits.
      shadow — RESOLVE-ONLY: turns with a cart are enqueued (with the cart slice) for the
               offline worker to resolve into plans — measured, logged, NEVER executed, zero
               added latency on the hot path. The soak that must precede serving.
      on     — inline serve (C1 gates: confidence floor now; risk-tiered confirmation to come).
    """
    raw = str(os.getenv("RECOMMEND_CART_SERVE", "") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return "on"
    if raw == "shadow":
        return "shadow"
    return "off"


# below this, a model-resolved plan with executable ops is NOT served inline — the turn falls
# through to legacy/frontend (parallel-run net). Asking a clarification is safe at any confidence.
_MIN_EXEC_CONFIDENCE = 0.5


def _cart_auto_apply_enabled() -> bool:
    """Auto-apply a single reversible op WITHOUT a confirm click. OFF by default (review-6
    #4/#13): confirmation-only until the measured false-positive rate on carted search turns is
    low enough. Flip RECOMMEND_CART_AUTO_APPLY=1 only then."""
    return str(os.getenv("RECOMMEND_CART_AUTO_APPLY", "") or "").strip().lower() in ("1", "true", "yes", "on")


def _read_cart_slice(db, uid: str, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The shopper's current cart lines with DISPLAY NAMES (the resolver binds a named line by
    name, so raw sku+qty lines aren't enough). Read-only: never creates a cart. Best-effort —
    a read failure yields no cart, so the turn simply routes as a normal search.
    Tenant-scoped (R10.2): explicit arg → request ContextVar → 'default'."""
    if not uid:
        return []
    try:
        from sqlalchemy import text as _text
        if not tenant_id:
            from src.app.platform.tenant_context import current_tenant_id
            tenant_id = current_tenant_id()
        row = db.execute(_text("SELECT line_items FROM draft_orders WHERE customer_id = :uid "
                               "AND tenant_id = :t AND status = 'draft' "
                               "ORDER BY created_at DESC LIMIT 1"),
                         {"uid": str(uid), "t": str(tenant_id)}).fetchone()
        raw = json.loads(row[0]) if row and row[0] else []
        items = raw if isinstance(raw, list) else []
        skus = [str(it.get("sku")) for it in items if isinstance(it, dict) and it.get("sku")]
        if not skus:
            return []
        params = {f"s{i}": s for i, s in enumerate(skus)}
        placeholders = ", ".join(f":{k}" for k in params)
        names = {str(r[0]): str(r[1] or "") for r in db.execute(
            _text(f"SELECT sku, name FROM products WHERE sku IN ({placeholders})"), params).fetchall()}
        out: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict) or not it.get("sku"):
                continue
            sku = str(it["sku"])
            out.append({"sku": sku, "name": names.get(sku, ""),
                        "quantity": int(it.get("quantity") or 1),
                        "sourcing_required": bool(it.get("sourcing_required")),
                        "available_now": it.get("available_now")})
        return out
    except Exception as exc:
        logger.debug("cart slice read skipped: %s", repr(exc)[:100])
        return []


def _cart_result_message(plan, result: Dict[str, Any]) -> str:
    """Honest buyer-facing summary of what actually changed (applied), what didn't (rejected,
    with the real stock reason), and what stayed ambiguous (asked, never wiped)."""
    applied = result.get("applied", [])
    rejected = result.get("rejected", [])
    bits: List[str] = []
    if any(a.get("action") == "clear_all" for a in applied):
        bits.append("cleared your cart")
    n_removed = sum(1 for a in applied if a.get("action") == "remove_items")
    if n_removed:
        bits.append(f"removed {n_removed} item{'s' if n_removed != 1 else ''}")
    for a in applied:
        if a.get("action") != "set_quantity":
            continue
        src = a.get("sourcing")
        if src:
            bits.append(f"set a line to {a.get('quantity')} ({src.get('available_now')} in stock "
                        f"now, {src.get('shortfall')} to source)")
        else:
            bits.append(f"set a line to {a.get('quantity')}")
    msg = ("🧹 Done — " + ", ".join(bits) + ".") if bits else "No cart change was needed."
    if rejected:
        err = rejected[0].get("error")
        if isinstance(err, dict) and err.get("available") is not None:
            msg += (f" One change couldn't be applied — only {err.get('available')} in stock; "
                    f"say \"source the rest\" to order the shortfall.")
        else:
            msg += " One change couldn't be applied."
    if getattr(plan, "ambiguous", None):
        msg += (f" I couldn't match {', '.join(plan.ambiguous)} to a specific line — "
                f"tell me which item you meant.")
    return msg


def _cart_clarify_message(plan) -> str:
    return (f"I can edit your cart, but couldn't match {', '.join(plan.ambiguous)} to a specific "
            f"item in it — which line did you mean? Name it and I'll make the change.")


def _cart_confirm_message(plan) -> str:
    """The confirmation ask for a confirm-tier plan — states exactly what WILL happen; nothing
    has happened yet."""
    bits: List[str] = []
    for op in plan.ops:
        if op.action == "clear_all":
            bits.append("empty your whole cart")
        elif op.action == "clear_previous":
            bits.append("remove the items carried over from your earlier session")
        elif op.action == "keep_only":
            bits.append(f"remove everything except {len(op.target_skus)} item(s)")
        elif op.action == "remove_items":
            bits.append(f"remove {len(op.target_skus)} item(s)")
        elif op.action == "set_quantity":
            detail = f"change a line to {op.quantity} unit(s)"
            if op.allow_sourcing:
                detail += "; if stock is short, add the remainder to the supplier delivery plan"
            bits.append(detail)
        elif op.action == "replace_item":
            replacement = op.replacement_name or op.replacement_sku
            detail = f"replace one item with {replacement} at {op.quantity} unit(s)"
            if op.unit_price_cents is not None:
                each = op.unit_price_cents / 100
                total = each * int(op.quantity or 0)
                detail += f" (${each:,.0f} each; ${total:,.0f} total)"
            if op.previous_quantity is not None and op.previous_quantity != op.quantity:
                detail += f", changing the line from {op.previous_quantity} to {op.quantity} units"
            if op.budget_max_cents is not None:
                detail += f" to remain within the ${op.budget_max_cents / 100:,.0f} total budget"
            bits.append(detail)
    what = "; ".join(bits) or "apply that cart change"
    reconfirm = ""
    if any(op.action in {"set_quantity", "replace_item", "remove_items", "clear_all",
                         "clear_previous", "keep_only"} for op in plan.ops):
        reconfirm = (" After an inventory change, review and reconfirm the updated delivery plan "
                     "before checkout.")
    return (f"Just to confirm before I touch your cart — you want me to: {what}. "
            f"Nothing is changed yet; confirm and I'll apply it (undo stays available)."
            f"{reconfirm}")


def _serve_cart_mutation(envelope: TurnEnvelope, *, role: str,
                         with_trace: Callable[[Dict[str, Any], str], Dict[str, Any]],
                         llm_fn=None, redis=None) -> Optional[Dict[str, Any]]:
    """Detect + serve a natural-language cart edit. Returns a finalized payload when the turn IS a
    cart mutation, or None to fall through to product routing (empty plan = not a cart edit)."""
    from src.app.services.recommendation_core.cart_resolver import resolve_cart_mutation
    from src.app.services.recommendation_core.envelope import CoreResponse
    from src.app.services.recommendation_core.legacy_adapter import to_legacy

    plan = resolve_cart_mutation(envelope, llm_fn=llm_fn)
    if plan.is_empty:
        return None

    # ANY AMBIGUITY SUSPENDS THE WHOLE PLAN (review-5 #2): 'remove A and B' with B ambiguous
    # must NOT remove A and then ask — partial application of a compound instruction is a
    # mutation the shopper never approved. Ask about the unresolved names; execute nothing.
    if plan.needs_clarification:
        core = CoreResponse(envelope=envelope, lane="CART_MUTATE",
                            message=_cart_clarify_message(plan)).finalize()
        payload = to_legacy(core)
        payload["cart_mutation"] = {"applied": [], "rejected": [], "ambiguous": list(plan.ambiguous),
                                    "needs_clarification": True}
        payload["cart_updated"] = False
        return with_trace(payload, envelope.trace_id)

    # CONFIDENCE FLOOR (review-5 #9): a low-confidence plan with executable ops is not served —
    # fall through to legacy/frontend (parallel-run net catches it; shadow measures it).
    if plan.confidence < _MIN_EXEC_CONFIDENCE:
        logger.info("cart plan below exec confidence (%.2f < %.2f) — falling through",
                    plan.confidence, _MIN_EXEC_CONFIDENCE)
        return None

    # AUTHORIZE → EXECUTE via the C1 transactional boundary (review-5 #1/#3/#5): the plan is
    # PERSISTED against the cart state it was resolved on, then policy decides from its SHAPE —
    # auto (single-target reversible) applies now, all-or-nothing + idempotent + undo-stashed;
    # everything else returns a confirmation card that applies via
    # POST /cart/mutations/{plan_id}/apply. No inline mutation, no partial application, and a
    # trace-finalization failure can no longer follow a mutation into legacy (the apply is the
    # commit point; with_trace shapes a payload that reports what ALREADY durably happened).
    from src.app.domain.cart_mutation import RISK_AUTO
    from src.app.services.cart_mutation_service import apply_plan, propose_plan
    prop = propose_plan(tenant_id=envelope.tenant_id, uid=envelope.uid, plan=plan,
                        cart_items=envelope.cart, query=envelope.query,
                        trace_id=envelope.trace_id)
    # CONFIRMATION-ONLY BY DEFAULT (review-6 #4/#13): even the AUTO risk tier requires an explicit
    # confirm during the soak — a model false positive (or a hostile cart-line name) must not
    # remove/change a line without a human click. Auto-apply is a SEPARATE opt-in flipped ONLY
    # after the measured false-positive rate on ordinary carted turns is acceptably low.
    if prop["risk"] != RISK_AUTO or not _cart_auto_apply_enabled():
        core = CoreResponse(envelope=envelope, lane="CART_MUTATE",
                            message=_cart_confirm_message(plan)).finalize()
        payload = to_legacy(core)
        payload["cart_mutation"] = {"applied": [], "rejected": [], "ambiguous": [],
                                    "needs_clarification": False, "needs_confirmation": True,
                                    "plan_id": prop["plan_id"], "risk": prop["risk"],
                                    "ops": [o.as_dict() for o in plan.ops],
                                    "expires_at": prop["expires_at"]}
        payload["cart_updated"] = False
        return with_trace(payload, envelope.trace_id)

    outcome = apply_plan(prop["plan_id"], tenant_id=envelope.tenant_id, uid=envelope.uid,
                         redis=redis)
    status = outcome.get("status")
    applied = outcome.get("applied") or []
    rejected = ([{"action": "plan", "error": outcome.get("error")}]
                if status in ("rejected", "error") else [])
    result = {"applied": applied, "rejected": rejected}
    core = CoreResponse(envelope=envelope, lane="CART_MUTATE",
                        message=_cart_result_message(plan, result)).finalize()
    payload = to_legacy(core)
    payload["cart_mutation"] = {"applied": applied, "rejected": rejected, "ambiguous": [],
                                "needs_clarification": False, "plan_id": prop["plan_id"],
                                "status": status}
    if outcome.get("cart") is not None:
        payload["cart"] = outcome["cart"]
    # cart_updated must be the TRUTH (review-5 #9): the cart reflects the plan when it was
    # applied now OR was already applied by an earlier (idempotent-replayed) submit
    # (defect-hunt #7 — already_applied is a success, not a no-change).
    payload["cart_updated"] = status in ("applied", "already_applied") and bool(applied)
    return with_trace(payload, envelope.trace_id)


def _classified_subject(db, skus: List[str], tenant_id: str) -> Optional[str]:
    """Deepest shared approved subject for a delegated lane's exact shortlist."""
    if db is None or not skus:
        return None
    from sqlalchemy import text as _sql
    from src.app.services.taxonomy_registry import ancestors, get_node

    shortlist = [str(sku) for sku in skus if sku][:12]
    params = {f"s{i}": sku for i, sku in enumerate(shortlist)}
    params["t"] = tenant_id
    placeholders = ", ".join(f":s{i}" for i in range(len(shortlist)))
    try:
        rows = db.execute(_sql(
            "SELECT sku, node_handle FROM product_classification "
            f"WHERE tenant_id=:t AND status='approved' AND sku IN ({placeholders})"
        ), params).fetchall()
    except Exception as exc:
        logger.warning("legacy shortlist taxonomy bridge failed (tenant=%s): %s",
                       tenant_id, repr(exc)[:120])
        return None
    # A partial classification page is not sufficient evidence to narrow the whole slate.
    if len(rows) < max(1, (len(shortlist) * 4 + 4) // 5):
        return None
    chains = []
    for row in rows:
        node = get_node(str(row[1] or ""))
        if node is not None:
            chains.append({node.handle, *(item.handle for item in ancestors(node.handle))})
    if not chains:
        return None
    shared = set.intersection(*chains)
    nodes = [get_node(handle) for handle in shared]
    specific = [node for node in nodes if node is not None and node.depth >= 1]
    return max(specific, key=lambda node: (node.depth, node.handle)).handle if specific else None


def _read_session_slice(redis, uid: str, tenant_id: str, db: Any = None) -> Dict[str, Any]:
    """Best-effort immutable session slice, TENANT-SCOPED (GPT-5.6 #5c22575.3): the core's
    session namespace is session:{tenant}:{uid}:kv_state — never uid-alone (that would cross
    tenants). Consumed by prior-subject resolution later; populated now so the wiring is
    proven end-to-end."""
    if redis is None or not uid:
        return {}
    try:
        raw = redis.get(f"session:{tenant_id}:{uid}:kv_state")
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict) or not data:
            # Transitional bridge: delegated legacy lanes still write an unscoped key. It is
            # unsafe for named tenants, so only the single-tenant demo namespace may read it.
            # Delete this branch once all lane postflights write the canonical scoped slice.
            if tenant_id != "default":
                return {}
            legacy_raw = redis.get(f"session:{uid}:kv_state")
            legacy = json.loads(legacy_raw) if legacy_raw else {}
            if not isinstance(legacy, dict) or not legacy:
                return {}
            confirmed = legacy.get("confirmed_slots") or {}
            snapshot = (legacy.get("last_valid_constraints_snapshot")
                        or legacy.get("last_constraints_snapshot") or {})
            bmin = confirmed.get("budget_min", snapshot.get("budget_min"))
            bmax = confirmed.get("budget_max", snapshot.get("budget_max"))
            quantity = confirmed.get("order_quantity")
            total_budget_cents = confirmed.get("total_budget_cents")
            budget_scope = confirmed.get("budget_scope")
            try:
                bmin = int(round(float(bmin) * 100)) if bmin is not None else None
                bmax = int(round(float(bmax) * 100)) if bmax is not None else None
                quantity = int(quantity) if quantity is not None else None
                total_budget_cents = (int(total_budget_cents)
                                      if total_budget_cents is not None else None)
            except (TypeError, ValueError):
                bmin = bmax = quantity = total_budget_cents = None
            if total_budget_cents is not None and total_budget_cents <= 0:
                total_budget_cents = None
            if budget_scope not in {"total", "per_unit"}:
                budget_scope = None
            active_pr = legacy.get("active_pr")
            if isinstance(active_pr, dict):
                procurement_active = bool(active_pr.get("pr_id") and not active_pr.get("finalized"))
            else:
                procurement_active = bool(legacy.get("last_sourcing_intent"))
            shortlist = (legacy.get("last_valid_shortlist_skus")
                         or legacy.get("last_shortlist_skus") or [])
            return {
                "prior_node": _classified_subject(db, shortlist, tenant_id),
                # The mature legacy procurement workflow remains the executor. Bridge only its
                # explicit workflow state into the V2 routing context; do not infer procurement
                # from quantity alone because ordinary multi-pack searches also carry quantity.
                "prior_lane": "PROCUREMENT" if procurement_active else None,
                "active_workflow_lane": "PROCUREMENT" if procurement_active else None,
                "shortlist_skus": shortlist,
                "accepted_constraints": {
                    "budget_min_cents": bmin,
                    "budget_max_cents": bmax,
                    "total_budget_cents": total_budget_cents,
                    "budget_scope": budget_scope,
                    "requirements": {},
                    "quantity": quantity,
                },
                "legacy_bridge": True,
            }
        shortlist = data.get("last_shortlist_skus") or []
        return {"prior_node": (data.get("last_node_handle")
                               or _classified_subject(db, shortlist, tenant_id)),
                "prior_lane": data.get("last_lane"),
                "active_workflow_lane": data.get("active_workflow_lane"),
                "shortlist_skus": shortlist,
                "accepted_constraints": data.get("constraints") or {}}
    except Exception:
        return {}


def _run_guard(*, query: str, uid: str, image_labels: Optional[str],
               image_ocr: Optional[str]) -> Dict[str, Any]:
    try:
        return inspect_commerce_request(
            surface="recommend.core", texts=[query, image_labels, image_ocr], uid=uid,
            sku_values=[], quantity_values=[])
    except Exception as exc:
        logger.warning("commerce guard failed in facade — failing closed to review: %s",
                       repr(exc)[:120])
        return {"verdict": "review", "severity": "medium", "reasons": ["guard_error"]}


def dispatch_recommendation_core_typed(
    db, redis, *, query: str, uid: str, tenant_id: Optional[str],
    budget_min: Optional[float], budget_max: Optional[float], trace_id: str,
    image_labels: Optional[str] = None, image_hash: Optional[str] = None,
    image_ocr: Optional[str] = None, source_ip: Optional[str] = None, request: Any = None,
    image_intent: Optional[str] = None, image_product_identity: Optional[str] = None,
    image_cv_signals: Optional[str] = None,
    intent_hint: Optional[str] = None,
    role: str = "",
    with_trace: Optional[Callable[[Dict[str, Any], str], Dict[str, Any]]] = None,
    record_failure: Optional[Callable[..., Any]] = None,
) -> FacadeOutcome:
    """Dispatch with explicit ownership and failure semantics."""
    dispatch_started = time.perf_counter()
    quota_budget = None
    quota_estimated = 0
    quota_recorded = False
    if record_failure is None:
        from src.app.services.safe_stage import record_partial_failure
        record_failure = record_partial_failure
    if with_trace is None:
        from src.app.services.recommendation_response_finalizer import finalize_core_response

        def with_trace(payload: Dict[str, Any], active_trace_id: str) -> Dict[str, Any]:
            payload = dict(payload or {})
            payload.setdefault("execution_mode", "v2_served")
            return finalize_core_response(
                payload, active_trace_id, query=query, tenant_id=tenant_id or "default", uid=uid,
            )

    def outcome(status: FacadeStatus, *, payload: Optional[Dict[str, Any]] = None,
                reason: str = "", lane: Optional[str] = None) -> FacadeOutcome:
        nonlocal quota_recorded
        if status == "served" and quota_budget is not None and not quota_recorded:
            try:
                from src.app.services.token_budget import estimate_cost
                quota_budget.record_usage(uid or "anonymous", quota_estimated,
                                          estimate_cost(quota_estimated))
                quota_recorded = True
            except Exception as exc:
                record_failure("recommend_facade_quota_record", exc, trace_id=trace_id)
        return FacadeOutcome(
            status=status, payload=payload, reason=reason, lane=lane,
            latency_ms=round((time.perf_counter() - dispatch_started) * 1000.0, 1),
        )

    mode, pct = _resolve_mode()
    cart_mode = _cart_mode()
    if mode == "off" and cart_mode == "off":
        return outcome("delegate", reason="mode_off")
    tenant = tenant_id or "default"

    # Universal quota admission belongs at the typed ingress. Legacy delegation retains its own
    # check during migration; checks are read-only, so delegation cannot double-charge usage.
    try:
        from src.app.services.token_budget import TokenBudget, estimate_tokens, infer_tier
        quota_budget = TokenBudget(redis)
        quota_estimated = estimate_tokens(query)
        allowed, quota_reason, _remaining = quota_budget.check_budget(
            uid or "anonymous", infer_tier(uid or "anonymous"), quota_estimated,
        )
        if not allowed:
            return outcome("blocked", reason=f"quota:{quota_reason}")
    except Exception as exc:
        record_failure("recommend_facade_quota", exc, trace_id=trace_id)
        return outcome("error", reason="quota_check_failed")

    # IMAGE V2 ingress: transform the legacy flat parameters into one bounded observation.
    # OCR remains guard-only. The trust posture determines which visual facts may influence
    # interpretation; taxonomy, eligibility, constraints and ranking remain core-owned.
    image_observations = []
    if image_labels or image_hash or image_product_identity or image_cv_signals:
        from src.app.services.recommendation_core.envelope import ImageObservation
        try:
            signals = json.loads(image_cv_signals) if image_cv_signals else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            signals = {}
        try:
            identity = json.loads(image_product_identity) if image_product_identity else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            identity = {}
        if not isinstance(signals, dict):
            signals = {}
        if not isinstance(identity, dict):
            identity = {}
        hostile = bool(signals.get("qr_prompt_injection") or signals.get("ocr_prompt_injection")
                       or signals.get("pii_detected") or signals.get("ssn_detected")
                       or float(signals.get("adversarial_score") or 0) >= 0.7)
        review = bool(signals.get("qr_code_detected") or signals.get("steg_suspicious")
                      or signals.get("fast_triage_timeout"))
        trust_mode = "text_only" if hostile else ("sanitized" if review else "full")
        analysis_state = ("pending" if signals.get("fast_triage_timeout")
                          else "degraded" if signals.get("analysis_degraded") else "complete")
        labels = [part.strip() for part in str(image_labels or "").split(",") if part.strip()]
        image_observations.append(ImageObservation.bounded(
            labels=labels, product_identity=identity, image_hash=image_hash,
            analysis_state=analysis_state, trust_mode=trust_mode))

    # ── CART-MUTATION LANE — its OWN ladder, independent of the search mode ──────
    # RECOMMEND_CART_SERVE=on: inline serve (below). =shadow: RESOLVE-ONLY — handled at the
    # shadow enqueue point further down (zero hot-path latency, zero execution). A natural-
    # language cart edit ('remove one item and set another to 20') is not a product search;
    # resolve it to a typed, SKU-bound plan and execute via the guarded cart handlers. A miss
    # (empty plan / low confidence / ambiguity-ask / failure) falls through to the search ladder,
    # which the frontend regex still backstops (parallel-run). Image turns never cart-serve.
    _served_guard: Optional[Dict[str, Any]] = None
    if cart_mode == "on" and not (image_labels or image_hash):
        try:
            _served_guard = _run_guard(query=query, uid=uid, image_labels=image_labels,
                                       image_ocr=image_ocr)
            if str(_served_guard.get("verdict")) == "allow":
                cart_slice = _read_cart_slice(db, uid, tenant_id=tenant)
                if cart_slice:
                    envelope = TurnEnvelope.from_suggest_params(
                        query=query, uid=uid or "", tenant_id=tenant, budget_min=budget_min,
                        budget_max=budget_max, trace_id=trace_id, has_image=False,
                        intent_hint=intent_hint,
                        source_ip=source_ip, session=_read_session_slice(redis, uid, tenant, db),
                        cart=cart_slice, pre_gate=_served_guard)
                    cart_payload = _serve_cart_mutation(envelope, role=role,
                                                        with_trace=with_trace, redis=redis)
                    if cart_payload is not None:
                        logger.info("core served CART_MUTATE (uid=%s)", uid or "anon")
                        return outcome("served", payload=cart_payload, lane="CART_MUTATE")
        except Exception as exc:
            record_failure("recommend_cart_dispatch", exc, trace_id=trace_id)
            _served_guard = None   # a guard from a failed cart attempt is not reused

    # ── SHADOW ENQUEUE (search shadow and/or cart resolve-only, ONE enqueue per turn) ──
    # Search shadow enqueues EVERY turn (review #8: image turns included — excluding them would
    # overstate coverage). Cart resolve-only (cart_mode==shadow) attaches the cart slice so the
    # worker resolves a plan OFFLINE — measured, never executed, no hot-path model call
    # (review-5 #6: the inline-12s/SSE-abort duplication concern doesn't exist in this mode).
    if mode == "shadow" or cart_mode == "shadow":
        cart_slice: List[Dict[str, Any]] = []
        if cart_mode == "shadow" and uid and not (image_labels or image_hash):
            cart_slice = _read_cart_slice(db, uid, tenant_id=tenant)
        if mode == "shadow" or cart_slice:
            # FULL envelope in the job (R10.1/P1.1): budget/session/image ride along so the
            # worker replays the turn production actually saw, not a query-only shadow of it.
            shadow_env = TurnEnvelope.from_suggest_params(
                query=query, uid=uid or "", tenant_id=tenant, budget_min=budget_min,
                budget_max=budget_max, trace_id=trace_id,
                intent_hint=intent_hint,
                has_image=bool(image_labels or image_hash), source_ip=source_ip,
                image_observations=image_observations,
                session=_read_session_slice(redis, uid, tenant, db), cart=cart_slice)
            _enqueue_shadow(redis, envelope=shadow_env, cart_only=(mode != "shadow"))
        if mode == "shadow":
            return outcome("delegate", reason="shadow_only")

    # ── SEARCH-LANE MODE LADDER ─────────────────────────────────────────────────
    if mode == "off":
        return outcome("delegate", reason="search_mode_off")

    # IMAGE is a modality, not a second product-selection lane. Policy-filtered observations
    # ride the shared envelope; the lane and every consequential decision remain clamped below.
    # canary bucket on tenant:uid (GPT-5.6 #5c22575.4) — same user in different tenants can
    # legitimately land different sides; anon users bucket by tenant.
    if mode == "canary" and not _in_canary_bucket(f"{tenant}:{uid or 'anon'}", pct):
        return outcome("delegate", reason="outside_canary_bucket")

    try:
        # ── PREFLIGHT: the real shared guard (finding #1/#10). Reuse the cart path's verdict if
        # it already ran this turn (same query/uid); else run it now. Require verdict==allow
        # (GPT-5.6 #5c22575.1): a flagged query must never be core-served with products.
        guard = _served_guard or _run_guard(query=query, uid=uid, image_labels=image_labels,
                                            image_ocr=image_ocr)
        if str(guard.get("verdict")) != "allow":
            return outcome("blocked", reason=f"guard:{guard.get('verdict') or 'unknown'}")

        session = _read_session_slice(redis, uid, tenant, db)
        # the search core is cart-blind; cart editing already ran above (parallel-run).
        envelope = TurnEnvelope.from_suggest_params(
            query=query, uid=uid or "", tenant_id=tenant, budget_min=budget_min,
            budget_max=budget_max, trace_id=trace_id,
            intent_hint=intent_hint,
            has_image=bool(image_labels or image_hash), source_ip=source_ip,
            image_observations=image_observations,
            session=session, pre_gate=guard)

        # ── DISPATCH ───────────────────────────────────────────────────────────
        from src.app.services.recommendation_core.core import recommend_turn
        from src.app.services.recommendation_core.legacy_adapter import to_legacy
        _t0 = time.perf_counter()
        core = recommend_turn(db, envelope)
        _latency_ms = int((time.perf_counter() - _t0) * 1000)

        # A material clarification is safe across a delegated-lane boundary: it contains no
        # products and performs no procurement action. The answered turn is routed again, while
        # the mature workflow continues to own every sourcing and approval operation.
        material_clarification = any(
            str(item.get("reason") or "").startswith("missing_material_")
            for item in (core.clarify or []) if isinstance(item, dict)
        )
        if not _lane_is_enrolled(core.lane) and material_clarification and not core.products:
            payload = with_trace(to_legacy(core), trace_id)
            return outcome("served", payload=payload, lane="CLARIFY")

        # ── LANE GATE (finding #6): non-core lanes fall through to legacy ───────
        if not _lane_is_enrolled(core.lane):
            logger.debug("core lane %s not canary-eligible — falling through to legacy", core.lane)
            _fallback_metric(f"lane:{core.lane}")
            return outcome("delegate", reason="lane_not_enrolled", lane=core.lane)

        # DEGRADED → legacy (review #5): a core turn that couldn't verify the catalog
        # (grounding error / retrieval failure) must NOT serve a 'try again' apology to a
        # canary buyer while a healthy legacy sits one return away. Honest degradation only
        # falls back when it produced nothing — an off-catalog refusal is a real answer, keep it.
        if core.grounding in ("error", "empty") or (core.degraded and not core.products and not core.off_catalog):
            logger.info("core degraded (grounding=%s reason=%s) — falling through to legacy",
                        core.grounding, (core.extras or {}).get("degraded_reason"))
            _fallback_metric(f"grounding:{core.grounding}")
            return outcome("degraded", reason=f"grounding:{core.grounding}", lane=core.lane)

        # ── FINALIZE FIRST, THEN POSTFLIGHT (review #3): with_trace (sanitize + trace
        # persistence) must SUCCEED before any session mutation. If it raises, the outer except
        # returns None → legacy serves, and session state was NOT yet written by V2 — no
        # split-brain where V2 mutated session but legacy answered.
        payload = with_trace(to_legacy(core), trace_id)
        try:
            from src.app.services.recommendation_postflight import run_postflight
            run_postflight(redis, envelope, core, latency_ms=_latency_ms)
        except Exception as _e_pf:
            logger.warning("postflight failed (non-fatal): %s", repr(_e_pf)[:120])
        return outcome("served", payload=payload, lane=core.lane)
    except Exception as exc:
        record_failure("recommend_core_dispatch", exc, trace_id=trace_id)
        return outcome("error", reason=type(exc).__name__)


def dispatch_recommendation_core(
    db, redis, *, query: str, uid: str, tenant_id: Optional[str],
    budget_min: Optional[float], budget_max: Optional[float], trace_id: str,
    image_labels: Optional[str] = None, image_hash: Optional[str] = None,
    image_ocr: Optional[str] = None, source_ip: Optional[str] = None, request: Any = None,
    image_intent: Optional[str] = None, image_product_identity: Optional[str] = None,
    image_cv_signals: Optional[str] = None,
    intent_hint: Optional[str] = None,
    role: str = "",
    with_trace: Callable[[Dict[str, Any], str], Dict[str, Any]] = lambda payload, _trace: payload,
    record_failure: Callable[..., Any] = lambda *_args, **_kwargs: None,
) -> Optional[Dict[str, Any]]:
    """Payload-or-None compatibility edge while routers migrate to typed outcomes."""
    result = dispatch_recommendation_core_typed(
        db, redis, query=query, uid=uid, tenant_id=tenant_id,
        budget_min=budget_min, budget_max=budget_max, trace_id=trace_id,
        image_labels=image_labels, image_hash=image_hash, image_ocr=image_ocr,
        source_ip=source_ip, request=request, image_intent=image_intent,
        image_product_identity=image_product_identity, image_cv_signals=image_cv_signals,
        intent_hint=intent_hint, role=role, with_trace=with_trace,
        record_failure=record_failure,
    )
    return result.payload if result.served else None
