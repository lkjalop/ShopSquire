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
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

_REORDER_RE = re.compile(r"\b(?:again|reorder|re-?order|last\s+time|previous\s+order|bought|purchased)\b", re.I)


@dataclass(frozen=True)
class EvidenceBudget:
    """Provider-neutral limits; cost units are relative, not currency claims."""

    per_lane_ms: int = 2500
    total_ms: int = 3000
    max_cost_units: int = 12


_LEG_COST_UNITS = {
    "market": 3,
    "policy": 1,
    "availability": 1,
    "purchase_history": 1,
    "image": 2,
    "web": 5,
}


def _table_has_column(db: Any, table: str, column: str) -> bool:
    """Schema capability check used to fail closed on tenant-sensitive reads."""
    try:
        from sqlalchemy import inspect
        return any(str(item.get("name") or "") == column
                   for item in inspect(db.get_bind()).get_columns(table))
    except Exception:
        return False


def orchestrator_enabled() -> bool:
    return str(os.getenv("EVIDENCE_ORCHESTRATOR_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _leg_budget_s() -> float:
    try:
        return max(0.5, float(os.getenv("EVIDENCE_LEG_BUDGET_SEC", "2.5") or 2.5))
    except (TypeError, ValueError):
        return 2.5


def select_legs(plan: Any, *, query: str = "", uid: Optional[str] = None,
                image_identity: Optional[Dict[str, Any]] = None,
                web_consent: bool = False) -> List[str]:
    """Which evidence legs does THIS turn need? Driven by the (possibly LLM-filled) plan — the whole
    point of R2: the reader decides the scatter, so simple turns fan out to nothing.

    The WEB leg is CONSENT-GATED (N3, Mode B): it is never selected from query content alone — the
    buyer must have explicitly accepted the "check an approved external source" chip this turn
    (web_consent=True), AND the operator flag/allowlist must resolve enabled. A user typing "search
    the web for X" therefore cannot force a fetch; the imperative only surfaces the consent chip."""
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
    if web_consent and str(os.getenv("EXTERNAL_RESEARCH_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        legs.append("web")
    return legs


def _templated_web_query(plan: Any) -> str:
    """Outbound query built ONLY from controlled vocabulary — plan slots whose values come from the
    profile/KB, never free user text. The user influences WHETHER a lookup happens; never the bytes
    on the wire (N3 exfiltration/SSRF posture)."""
    parts: List[str] = []
    for uc in (getattr(plan, "use_cases", []) or [])[:2]:
        parts.append(str(uc).replace("_", " "))
    if getattr(plan, "category", None):
        parts.append(str(plan.category))
    parts.append("buying guide requirements")
    return " ".join(p for p in parts if p).strip()


# ── Leg implementations (deterministic reads; each independently best-effort) ──

def _leg_market(plan: Any, query: str, uid: Optional[str], *,
                tenant_id: Optional[str] = None) -> Dict[str, Any]:
    from src.app.models.db import db_session
    from src.app.services.market_intelligence_agent import gather_market_context
    with db_session() as db:
        category = str(getattr(plan, "category", None) or "").strip()
        ctx = gather_market_context(db, query=query, uid_hash=None, result_skus=None,
                                    taxonomy_nodes=([category] if category else []),
                                    tenant_id=tenant_id)
    findings = ctx.get("market_findings") or []
    provenance_complete = bool(findings) and all(
        f.get("source_system") and f.get("observed_at") and f.get("status", "active") == "active"
        for f in findings
    )
    return {"source": "market_intelligence", "found": bool(findings),
            "summary": (ctx.get("narration_note") or "")[:400],
            "data": {"findings": findings[:5], "evidence_kinds": ctx.get("evidence_kinds") or [],
                     "trust_state": "verified_internal" if provenance_complete else "advisory",
                     "provenance_complete": provenance_complete}}


def _leg_policy(plan: Any, query: str, uid: Optional[str], *,
                tenant_id: Optional[str] = None) -> Dict[str, Any]:
    from src.app.services.answer_quality import policy_faq_answer
    ans = policy_faq_answer(query or "")
    return {"source": "store_policy", "found": bool(ans), "summary": (ans or "")[:400], "data": {}}


def _leg_availability(plan: Any, query: str, uid: Optional[str], *,
                      tenant_id: Optional[str] = None) -> Dict[str, Any]:
    from sqlalchemy import text
    from src.app.models.db import db_session
    category = getattr(plan, "category", None)
    qty = int(getattr(plan, "quantity", None) or 0)
    with db_session() as db:
        if not tenant_id or not _table_has_column(db, "inventory_level", "tenant_id"):
            return {"source": "inventory", "found": False, "summary": "", "data": {},
                    "error": "tenant_scope_unavailable"}
        row = db.execute(text(
            "SELECT COUNT(DISTINCT sku), "
            "COALESCE(SUM(COALESCE(available, on_hand - reserved)), 0) "
            "FROM inventory_level WHERE tenant_id = :tenant"),
            {"tenant": tenant_id}).fetchone()
    skus, units = int(row[0] or 0), int(row[1] or 0)
    summary = f"{skus} tenant inventory line(s) with {units} unit(s) available"
    if qty:
        summary += f" vs {qty} requested"
    return {"source": "inventory", "found": skus > 0,
            "summary": summary, "data": {"sku_count": skus, "units_available": units,
                                               "requested_qty": qty, "scope": "tenant_inventory",
                                               "requested_category": category}}


def _leg_purchase_history(plan: Any, query: str, uid: Optional[str], *,
                          tenant_id: Optional[str] = None) -> Dict[str, Any]:
    from sqlalchemy import text
    from src.app.models.db import db_session
    if not uid:
        return {"source": "purchase_history", "found": False, "summary": "", "data": {}}
    with db_session() as db:
        if not tenant_id or not _table_has_column(db, "orders", "tenant_id"):
            return {"source": "purchase_history", "found": False, "summary": "", "data": {},
                    "error": "tenant_scope_unavailable"}
        rows = db.execute(text(
            "SELECT id, status, total_cents, created_at FROM orders "
            "WHERE customer_id = :u AND tenant_id = :tenant "
            "ORDER BY created_at DESC LIMIT 3"), {"u": uid, "tenant": tenant_id}).fetchall()
    orders = [{"order_id": str(r[0]), "status": str(r[1] or ""), "total_cents": int(r[2] or 0),
               "created_at": str(r[3] or "")} for r in rows or []]
    summary = f"{len(orders)} recent order(s)" + (f", latest {orders[0]['status']}" if orders else "")
    return {"source": "purchase_history", "found": bool(orders), "summary": summary, "data": {"orders": orders}}


def _leg_image(plan: Any, query: str, uid: Optional[str], image_identity: Optional[Dict[str, Any]] = None,
               *, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    ident = image_identity or {}
    bits = [str(ident.get(k)) for k in ("brand", "model", "category") if ident.get(k)]
    return {"source": "image_identity", "found": bool(bits),
            "summary": ("photo identified as " + " ".join(bits)) if bits else "", "data": dict(ident)}


def _leg_web(plan: Any, query: str, uid: Optional[str], *,
             tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Governed external research leg (N3). Reuses the SSRF-safe guardrailed service end-to-end
    (allowlist from profile, size-bounded single-endpoint fetch, cache). Adds the inbound-content
    governance this leg owes on top: every snippet is injection-scanned (same detector as OCR text);
    flagged snippets are DROPPED and counted — the scan verdict is part of the evidence, never
    hidden. The outbound query is TEMPLATED from plan slots (zero user tokens)."""
    from src.app.services.external_product_research_service import run_external_research_stage
    templated = _templated_web_query(plan)
    res = run_external_research_stage(query=templated, results=None, tenant_id=tenant_id)
    if res is None:
        return {"source": "external_web", "found": False, "summary": "", "data": {"disabled": True}}
    items = res.get("items") or []
    try:
        from src.app.security.image_threat_signals import detect_ocr_prompt_injection as _inj
    except Exception:
        _inj = None
    clean, dropped = [], 0
    for it in items:
        text = f"{it.get('title') or ''} {it.get('snippet') or ''}"
        if _inj is not None and _inj(text):
            dropped += 1          # instruction-like web text is an ATTACK ARTIFACT, not evidence
            continue
        clean.append(it)
    top = clean[0] if clean else {}
    summary = (f"{top.get('snippet') or top.get('title') or ''}"[:300] +
               (f" — {top.get('source_domain')}" if top.get("source_domain") else "")) if clean else ""
    return {
        "source": "external_web",
        "found": bool(clean),
        "summary": summary,
        "data": {
            "query_templated": templated,       # provable: no user tokens on the wire
            "items": clean[:4],
            "injection_scan": {"checked": len(items), "dropped": dropped,
                               "verdict": "CLEAN" if dropped == 0 else f"{dropped} snippet(s) dropped"},
            "authority": "informs wording only — never ranks, prices or approves",
        },
    }


_LEG_FNS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "market": _leg_market,
    "policy": _leg_policy,
    "availability": _leg_availability,
    "purchase_history": _leg_purchase_history,
    "image": _leg_image,
    "web": _leg_web,
}


def gather_evidence(plan: Any, *, query: str = "", uid: Optional[str] = None,
                    image_identity: Optional[Dict[str, Any]] = None,
                    leg_fns: Optional[Dict[str, Callable[..., Dict[str, Any]]]] = None,
                    budget_s: Optional[float] = None,
                    evidence_budget: Optional[EvidenceBudget] = None,
                    web_consent: bool = False,
                    tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Run the selected legs concurrently under a per-leg budget. Returns
    {selected, legs: {name: leg_dict}, citations: [{source, summary}], ms}. Never raises;
    a timed-out/failed leg reports found=False with an error note instead of vanishing silently."""
    t0 = time.perf_counter()
    selected = select_legs(plan, query=query, uid=uid, image_identity=image_identity, web_consent=web_consent)
    configured = evidence_budget or EvidenceBudget(
        per_lane_ms=max(1, int((budget_s if budget_s is not None else _leg_budget_s()) * 1000)),
        total_ms=max(1, int((budget_s if budget_s is not None else _leg_budget_s()) * 1000)),
    )
    out: Dict[str, Any] = {
        "selected": selected,
        "legs": {},
        "citations": [],
        "contradictions": [],
        "source_health": "healthy",
        "budget": {
            "per_lane_ms": configured.per_lane_ms,
            "total_ms": configured.total_ms,
            "max_cost_units": configured.max_cost_units,
            "used_cost_units": 0,
        },
        "ms": 0,
    }
    if not selected:
        return out
    fns = leg_fns or _LEG_FNS
    admitted: list[str] = []
    used_cost = 0
    for name in selected:
        cost = int(_LEG_COST_UNITS.get(name, 1))
        if used_cost + cost > configured.max_cost_units:
            out["legs"][name] = {
                "source": name, "found": False, "summary": "", "data": {},
                "error": "cost_budget_exceeded", "health": "cancelled",
            }
            continue
        admitted.append(name)
        used_cost += cost
    out["budget"]["used_cost_units"] = used_cost
    if not admitted:
        out["source_health"] = "degraded"
        return out

    def _run(name: str) -> Dict[str, Any]:
        fn = fns.get(name)
        if fn is None:
            return {"source": name, "found": False, "summary": "", "data": {}, "error": "no_leg_fn"}
        try:
            if name == "image":
                return fn(plan, query, uid, image_identity=image_identity, tenant_id=tenant_id)
            return fn(plan, query, uid, tenant_id=tenant_id)
        except Exception as exc:   # a broken leg is EVIDENCE of a problem, not silence
            return {"source": name, "found": False, "summary": "", "data": {}, "error": str(exc)[:160]}

    tasks: queue.Queue[Optional[str]] = queue.Queue()
    completed = {name: threading.Event() for name in admitted}
    results: Dict[str, Dict[str, Any]] = {}

    def _worker() -> None:
        while True:
            name = tasks.get()
            if name is None:
                return
            results[name] = _run(name)
            completed[name].set()

    # Python threads cannot be killed safely. Executor workers are non-daemon,
    # so abandoning a timed-out future can keep a process alive. Daemon workers
    # preserve concurrent collection while ensuring a hung read cannot stall
    # interpreter shutdown. Individual legs must also keep transport deadlines.
    workers = [
        threading.Thread(
            target=_worker,
            name=f"evidence-leg-{index}",
            daemon=True,
        )
        for index in range(min(5, len(admitted)))
    ]
    for worker in workers:
        worker.start()
    for name in admitted:
        tasks.put(name)
    for _worker_thread in workers:
        tasks.put(None)

    launched_at = time.perf_counter()
    total_deadline = launched_at + configured.total_ms / 1000.0
    lane_deadline = launched_at + configured.per_lane_ms / 1000.0
    for name in admitted:
        remaining = max(0.0, min(total_deadline, lane_deadline) - time.perf_counter())
        if completed[name].wait(timeout=remaining):
            out["legs"][name] = results[name]
        else:
            out["legs"][name] = {
                "source": name,
                "found": False,
                "summary": "",
                "data": {},
                "error": f"leg_timeout>{configured.per_lane_ms}ms",
                "health": "timed_out",
            }
    for name in selected:
        leg = out["legs"].get(name) or {}
        if "health" not in leg:
            if leg.get("error"):
                leg["health"] = "failed"
            elif not leg.get("found"):
                leg["health"] = "empty"
            else:
                data = leg.get("data") if isinstance(leg.get("data"), dict) else {}
                leg["health"] = "degraded" if (
                    data.get("trust_state") == "advisory"
                    or (data.get("injection_scan") or {}).get("dropped", 0)
                ) else "healthy"
        if leg.get("found") and leg.get("summary"):
            data = leg.get("data") if isinstance(leg.get("data"), dict) else {}
            citation = {"source": leg.get("source") or name, "summary": leg["summary"]}
            if data.get("trust_state"):
                citation["trusted"] = data.get("trust_state") == "verified_internal"
            out["citations"].append(citation)
    claims: dict[str, list[dict[str, Any]]] = {}
    for name, leg in out["legs"].items():
        data = leg.get("data") if isinstance(leg.get("data"), dict) else {}
        for claim in data.get("claims") or []:
            if not isinstance(claim, dict) or not claim.get("key"):
                continue
            claims.setdefault(str(claim["key"]), []).append({
                "source": str(leg.get("source") or name),
                "value": claim.get("value"),
                "scope": claim.get("scope"),
            })
    out["contradictions"] = [
        {"claim_key": key, "claims": values}
        for key, values in sorted(claims.items())
        if len({repr(item.get("value")) for item in values}) > 1
    ]
    health_values = {str(leg.get("health")) for leg in out["legs"].values()}
    if out["contradictions"] or health_values & {"failed", "timed_out", "cancelled", "degraded"}:
        out["source_health"] = "degraded"
    elif health_values and health_values <= {"empty"}:
        out["source_health"] = "empty"
    out["ms"] = int((time.perf_counter() - t0) * 1000)
    return out
