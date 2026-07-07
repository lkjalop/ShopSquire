"""Plan-driven evidence scatter-gather (R2, 2026-07-07 roadmap) — agnostic core.

The decomposed plan (rules + the LLM planner when it escalated) READS the query; this module
ORCHESTRATES: it selects which evidence legs the turn actually needs, runs them concurrently with a
hard per-leg budget, and returns labeled evidence + citations the response/trace can carry. The LLM
never fetches anything itself — legs are deterministic reads; the intelligence is in the SELECTION
(a market question fans out to price evidence, a support turn to purchase history + policy, an image
turn to the identified product) — the same bounded-autonomy split as everywhere else in the platform:
model proposes scope, deterministic code executes, trace records.

Legs (each returns {"source", "found", "summary", "data"}):
  market            — competitor/price findings (market_intelligence_agent, plan.needs_market_evidence)
  policy            — the store's APPROVED policy answer (policy_faq_answer) for policy-shaped asks
  availability      — stock depth for the plan's category when quantity/horizon matters
  purchase_history  — the buyer's recent orders (support/re-order turns only — not every query)
  image             — the CV-identified product (already computed upstream; labeled as evidence)

Flag-gated EVIDENCE_ORCHESTRATOR_ENABLED (default OFF). A hung leg NEVER blocks the turn: each runs
under EVIDENCE_LEG_BUDGET_SEC (default 2.5s) in a thread and times out to found=False. Never raises.
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

_REORDER_RE = re.compile(r"\b(?:again|reorder|re-?order|last\s+time|previous\s+order|bought|purchased)\b", re.I)


def orchestrator_enabled() -> bool:
    return str(os.getenv("EVIDENCE_ORCHESTRATOR_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _leg_budget_s() -> float:
    try:
        return max(0.5, float(os.getenv("EVIDENCE_LEG_BUDGET_SEC", "2.5") or 2.5))
    except (TypeError, ValueError):
        return 2.5


def select_legs(plan: Any, *, query: str = "", uid: Optional[str] = None,
                image_identity: Optional[Dict[str, Any]] = None) -> List[str]:
    """Which evidence legs does THIS turn need? Driven by the (possibly LLM-filled) plan — the whole
    point of R2: the reader decides the scatter, so simple turns fan out to nothing."""
    legs: List[str] = []
    intent = str(getattr(plan, "intent", "") or "").lower()
    if getattr(plan, "needs_market_evidence", False):
        legs.append("market")
    if intent in ("support", "knowledge") or "policy" in str(query or "").lower():
        legs.append("policy")
    if (getattr(plan, "quantity", None) or 0) >= 2 or getattr(plan, "availability_horizon_days", None):
        legs.append("availability")
    if uid and (intent == "support" or _REORDER_RE.search(str(query or ""))):
        legs.append("purchase_history")
    if isinstance(image_identity, dict) and any(image_identity.get(k) for k in ("brand", "model", "category")):
        legs.append("image")
    return legs


# ── Leg implementations (deterministic reads; each independently best-effort) ──

def _leg_market(plan: Any, query: str, uid: Optional[str]) -> Dict[str, Any]:
    from src.app.models.db import db_session
    from src.app.services.market_intelligence_agent import gather_market_context
    with db_session() as db:
        ctx = gather_market_context(db, query=query, uid_hash=None, result_skus=None)
    findings = ctx.get("market_findings") or []
    return {"source": "market_intelligence", "found": bool(findings),
            "summary": (ctx.get("narration_note") or "")[:400],
            "data": {"findings": findings[:5], "evidence_kinds": ctx.get("evidence_kinds") or []}}


def _leg_policy(plan: Any, query: str, uid: Optional[str]) -> Dict[str, Any]:
    from src.app.services.answer_quality import policy_faq_answer
    ans = policy_faq_answer(query or "")
    return {"source": "store_policy", "found": bool(ans), "summary": (ans or "")[:400], "data": {}}


def _leg_availability(plan: Any, query: str, uid: Optional[str]) -> Dict[str, Any]:
    from sqlalchemy import text
    from src.app.models.db import db_session
    category = getattr(plan, "category", None)
    qty = int(getattr(plan, "quantity", None) or 0)
    with db_session() as db:
        row = db.execute(text(
            "SELECT COUNT(DISTINCT p.sku), COALESCE(SUM(i.stock), 0) FROM products p "
            "LEFT JOIN inventory i ON i.product_id = p.id "
            "WHERE p.active = 1" + (" AND p.product_type = :cat" if category else "")),
            ({"cat": category} if category else {})).fetchone()
    skus, units = int(row[0] or 0), int(row[1] or 0)
    summary = f"{skus} product(s) with {units} unit(s) on hand" + (f" vs {qty} requested" if qty else "")
    return {"source": "inventory", "found": skus > 0,
            "summary": summary, "data": {"sku_count": skus, "units_on_hand": units, "requested_qty": qty}}


def _leg_purchase_history(plan: Any, query: str, uid: Optional[str]) -> Dict[str, Any]:
    from sqlalchemy import text
    from src.app.models.db import db_session
    if not uid:
        return {"source": "purchase_history", "found": False, "summary": "", "data": {}}
    with db_session() as db:
        rows = db.execute(text(
            "SELECT id, status, total_cents, created_at FROM orders "
            "WHERE customer_id = :u ORDER BY created_at DESC LIMIT 3"), {"u": uid}).fetchall()
    orders = [{"order_id": str(r[0]), "status": str(r[1] or ""), "total_cents": int(r[2] or 0),
               "created_at": str(r[3] or "")} for r in rows or []]
    summary = f"{len(orders)} recent order(s)" + (f", latest {orders[0]['status']}" if orders else "")
    return {"source": "purchase_history", "found": bool(orders), "summary": summary, "data": {"orders": orders}}


def _leg_image(plan: Any, query: str, uid: Optional[str], image_identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ident = image_identity or {}
    bits = [str(ident.get(k)) for k in ("brand", "model", "category") if ident.get(k)]
    return {"source": "image_identity", "found": bool(bits),
            "summary": ("photo identified as " + " ".join(bits)) if bits else "", "data": dict(ident)}


_LEG_FNS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "market": _leg_market,
    "policy": _leg_policy,
    "availability": _leg_availability,
    "purchase_history": _leg_purchase_history,
    "image": _leg_image,
}


def gather_evidence(plan: Any, *, query: str = "", uid: Optional[str] = None,
                    image_identity: Optional[Dict[str, Any]] = None,
                    leg_fns: Optional[Dict[str, Callable[..., Dict[str, Any]]]] = None,
                    budget_s: Optional[float] = None) -> Dict[str, Any]:
    """Run the selected legs concurrently under a per-leg budget. Returns
    {selected, legs: {name: leg_dict}, citations: [{source, summary}], ms}. Never raises;
    a timed-out/failed leg reports found=False with an error note instead of vanishing silently."""
    t0 = time.perf_counter()
    selected = select_legs(plan, query=query, uid=uid, image_identity=image_identity)
    out: Dict[str, Any] = {"selected": selected, "legs": {}, "citations": [], "ms": 0}
    if not selected:
        return out
    fns = leg_fns or _LEG_FNS
    budget = budget_s if budget_s is not None else _leg_budget_s()

    def _run(name: str) -> Dict[str, Any]:
        fn = fns.get(name)
        if fn is None:
            return {"source": name, "found": False, "summary": "", "data": {}, "error": "no_leg_fn"}
        try:
            if name == "image":
                return fn(plan, query, uid, image_identity=image_identity)
            return fn(plan, query, uid)
        except Exception as exc:   # a broken leg is EVIDENCE of a problem, not silence
            return {"source": name, "found": False, "summary": "", "data": {}, "error": str(exc)[:160]}

    # NOT a `with` block: the context manager JOINS all threads on exit, so one hung leg would still
    # block the turn even after its result() timed out. shutdown(wait=False) abandons stragglers —
    # legs are bounded read-only fetches, safe to orphan; the timeout is recorded, never silent.
    pool = ThreadPoolExecutor(max_workers=min(5, len(selected)))
    try:
        futures = {name: pool.submit(_run, name) for name in selected}
        deadline = time.perf_counter() + budget
        for name, fut in futures.items():
            remaining = max(0.05, deadline - time.perf_counter())
            try:
                out["legs"][name] = fut.result(timeout=remaining)
            except Exception:
                out["legs"][name] = {"source": name, "found": False, "summary": "", "data": {},
                                     "error": f"leg_timeout>{budget}s"}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    for name in selected:
        leg = out["legs"].get(name) or {}
        if leg.get("found") and leg.get("summary"):
            out["citations"].append({"source": leg.get("source") or name, "summary": leg["summary"]})
    out["ms"] = int((time.perf_counter() - t0) * 1000)
    return out
