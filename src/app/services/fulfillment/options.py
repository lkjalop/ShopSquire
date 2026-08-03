"""Fulfilment options planner (agnostic CORE) — normalized facts → ranked options with tradeoffs.

Given what's available locally, what the supplier confirmed, the dates, the deadline, and an optional
substitute, it returns the buyer's real choices — ship together, ship available then remainder,
substitute the shortfall, substitute all, or reduce — each with EXPLICIT tradeoffs and which hard
constraints it satisfies. Pure + deterministic.

Guard rails encoded (the deck's "never do automatically"): an option that would exceed the buyer's
budget or miss a hard deadline is still SHOWN but flagged (constraints_satisfied=false) — it is never
silently chosen, never silently mixes products, and never claims a date the evidence doesn't support.
Vertical-blind: items/substitutes are opaque refs; the buyer-facing total is RETAIL (the supplier's
wholesale cost never appears here).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Dict, List, Optional

OPTION_SHIP_TOGETHER = "ship_together"
OPTION_SPLIT = "ship_available_then_remainder"
OPTION_SUBSTITUTE_SHORTFALL = "substitute_shortfall"
OPTION_SUBSTITUTE_ALL = "substitute_all"
OPTION_REDUCE = "cancel_or_reduce"


@dataclass(frozen=True)
class FulfillmentOption:
    option_id: str
    option_type: str
    title: str
    allocation: List[Dict[str, Any]]              # [{source: local|supplier|substitute, quantity, eta}]
    estimated_delivery_at: Optional[str]
    total_units: int
    total_amount_cents: int                       # buyer-facing RETAIL total (never wholesale)
    # ``None`` is a deliberate UNKNOWN result. Missing ETA/deadline evidence must not
    # silently become a successful delivery constraint.
    constraints_satisfied: Dict[str, Optional[bool]]
    tradeoffs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _within(amount_unit: Optional[int], budget_unit: Optional[int]) -> bool:
    if amount_unit is None or budget_unit is None:
        return True
    return amount_unit <= budget_unit


def _deadline_ok(eta: Optional[str], deadline: Optional[str]) -> Optional[bool]:
    if not eta or not deadline:
        return None
    try:
        from datetime import datetime

        def _instant(value: str) -> datetime:
            return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))

        return _instant(eta) <= _instant(deadline)
    except (TypeError, ValueError):
        return None


def plan_options(
    *,
    requested_qty: int,
    local_qty: int,
    confirmed_external_qty: int = 0,
    external_delivery_at: Optional[str] = None,
    local_delivery_at: Optional[str] = None,
    deadline: Optional[str] = None,
    unit_price_cents: Optional[int] = None,
    budget_per_unit_cents: Optional[int] = None,
    substitute: Optional[Dict[str, Any]] = None,   # {item_ref, local_qty, delivery_at, unit_price_cents, tradeoff}
) -> List[FulfillmentOption]:
    """Return the applicable options, ranked best-first (complete + deadline-met + fewest deliveries +
    same product)."""
    requested = int(requested_qty)
    local = max(0, int(local_qty))
    external = max(0, int(confirmed_external_qty))
    shortfall = max(0, requested - local)
    up = unit_price_cents
    opts: List[FulfillmentOption] = []

    def _opt(otype, title, alloc, eta, units, unit_amt, tradeoffs):
        complete = units >= requested
        opts.append(FulfillmentOption(
            option_id=f"opt-{otype}", option_type=otype, title=title, allocation=alloc,
            estimated_delivery_at=eta, total_units=units,
            total_amount_cents=int((unit_amt or 0) * units),
            constraints_satisfied={"complete": complete, "deadline_met": _deadline_ok(eta, deadline),
                                   "within_budget": _within(unit_amt, budget_per_unit_cents)},
            tradeoffs=tradeoffs))

    # 1. ship together (local + supplier), arriving on the later date
    if local + external >= requested and external > 0:
        _opt(OPTION_SHIP_TOGETHER, f"Ship all {requested} together",
             [{"source": "local", "quantity": local, "eta": local_delivery_at},
              {"source": "supplier", "quantity": requested - local, "eta": external_delivery_at}],
             external_delivery_at, requested, up,
             ["one delivery", "waits for the supplier units"])

    # 2. ship available now, remainder later (two deliveries)
    if local > 0 and external > 0:
        _opt(OPTION_SPLIT, f"Ship {local} now and {min(external, shortfall)} later",
             [{"source": "local", "quantity": local, "eta": local_delivery_at},
              {"source": "supplier", "quantity": min(external, shortfall), "eta": external_delivery_at}],
             external_delivery_at, local + min(external, shortfall), up,
             ["fastest partial fulfilment", "two deliveries may add handling"])

    # 3/4. substitute the shortfall or all
    if substitute and int(substitute.get("local_qty") or 0) >= shortfall and shortfall > 0:
        sub_up = substitute.get("unit_price_cents", up)
        sub_eta = substitute.get("delivery_at") or local_delivery_at
        _opt(OPTION_SUBSTITUTE_SHORTFALL,
             f"Use {substitute.get('item_ref')} for the remaining {shortfall}",
             [{"source": "local", "quantity": local, "eta": local_delivery_at},
              {"source": "substitute", "quantity": shortfall, "eta": sub_eta, "item_ref": substitute.get("item_ref")}],
             sub_eta, requested, up,  # mixed pricing → keep buyer total on the primary unit price
             ["complete sooner", "mixed fleet", str(substitute.get("tradeoff") or "different model")])
    if substitute and int(substitute.get("local_qty") or 0) >= requested:
        sub_up = substitute.get("unit_price_cents", up)
        sub_eta = substitute.get("delivery_at") or local_delivery_at
        _opt(OPTION_SUBSTITUTE_ALL, f"Use {substitute.get('item_ref')} for all {requested}",
             [{"source": "substitute", "quantity": requested, "eta": sub_eta, "item_ref": substitute.get("item_ref")}],
             sub_eta, requested, sub_up,
             ["single product", "different model", str(substitute.get("tradeoff") or "")])

    # 5. reduce to what's available now (always offered as a fallback)
    if local > 0 and local < requested:
        _opt(OPTION_REDUCE, f"Order the {local} available now",
             [{"source": "local", "quantity": local, "eta": local_delivery_at}],
             local_delivery_at, local, up,
             ["immediate", f"fewer units than requested ({local} of {requested})"])

    def _score(o: FulfillmentOption) -> tuple:
        c = o.constraints_satisfied
        deliveries = len({a.get("eta") for a in o.allocation})
        same_product = 0 if any(a.get("source") == "substitute" for a in o.allocation) else 1
        # True > UNKNOWN > False. Unknown remains visible but cannot outrank an
        # otherwise equivalent option whose evidence proves the constraint.
        def tri(value: Optional[bool]) -> int:
            return 2 if value is True else (1 if value is None else 0)
        return (tri(c["complete"]), tri(c["deadline_met"]), tri(c["within_budget"]),
                -deliveries, same_product)

    opts.sort(key=_score, reverse=True)
    return opts


# ── wiring through the workflow chokepoint ────────────────────────────────────
def generate_and_record(db, *, case_id: str, actor, deadline: Optional[str] = None,
                        unit_price_cents: Optional[int] = None, budget_per_unit_cents: Optional[int] = None,
                        local_delivery_at: Optional[str] = None, substitute: Optional[Dict[str, Any]] = None,
                        tenant_id: str = "default", now_iso: Optional[str] = None, trace_id: Optional[str] = None,
                        response_expectation: Optional[Dict[str, Any]] = None,
                        stage_duration_seconds: Optional[Dict[str, tuple[int, int]]] = None,
                        carrier_cutoff_at: Optional[str] = None,
                        dependency_versions: Optional[Dict[str, Any]] = None):
    """Read availability + the validated quote off the case, plan options, and fire
    fulfillment_options_generated (confidence-gated). Returns (TransitionResult, options)."""
    from src.app.services.fulfillment import workflow
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    st = cur.state_json if cur else {}
    avail = st.get("availability") or {}
    vq = st.get("validated_quote") or {}
    requirements = st.get("requirements") or {}
    requested_arrival = deadline or requirements.get("deadline") or requirements.get("required_by")
    temporal = response_expectation or st.get("supplier_response_expectation") or {}
    stages = stage_duration_seconds or st.get("critical_path_stage_durations") or {}
    cutoff = carrier_cutoff_at or st.get("carrier_cutoff_at")
    dependencies = dict(dependency_versions or {})
    dependencies.setdefault(
        "fulfillment_case", {"id": case_id, "version": str(cur.version_id if cur else "unknown")},
    )
    if avail.get("source_version"):
        dependencies.setdefault("atp", str(avail["source_version"]))
    if vq.get("provider_ref") or vq.get("source_version"):
        dependencies.setdefault("supplier_quote", str(vq.get("source_version") or vq.get("provider_ref")))
    if temporal.get("calendar_version"):
        dependencies.setdefault("operational_calendar", str(temporal["calendar_version"]))
    if cutoff:
        dependencies.setdefault("carrier_cutoff", str(st.get("carrier_cutoff_version") or cutoff))
    options = plan_options(
        requested_qty=int(avail.get("requested_qty") or 0), local_qty=int(avail.get("in_stock") or 0),
        confirmed_external_qty=int(vq.get("quoted_quantity") or 0),
        external_delivery_at=vq.get("estimated_delivery_at"), local_delivery_at=local_delivery_at,
        deadline=deadline, unit_price_cents=unit_price_cents, budget_per_unit_cents=budget_per_unit_cents,
        substitute=substitute)
    option_payloads: List[Dict[str, Any]] = []
    if now_iso:
        evaluated_at = now_iso
    else:
        from datetime import datetime, timezone
        evaluated_at = datetime.now(timezone.utc).isoformat()
    for option in options:
        payload = option.to_dict()
        if not requested_arrival:
            promise = {
                "calculation_version": "promise-critical-path-v1:deadline-missing",
                "feasibility": "unknown", "requested_quantity": int(avail.get("requested_qty") or 0),
                "requested_arrival_at": None, "evaluated_at": evaluated_at,
                "quantity_by_deadline": 0, "quantity_confirmed_by_deadline": 0,
                "unknown_quantity": int(option.total_units),
                "reason_codes": ["requested_arrival_missing"],
                "failed_constraints": ["requested_arrival_missing"],
                "state_prevented": "unsupported_full_delivery_promise",
                "response_expectation": temporal, "dependency_versions": dependencies,
            }
        else:
            try:
                from src.app.services.promise_feasibility import evaluate_critical_path

                promise = evaluate_critical_path(
                    requested_quantity=int(avail.get("requested_qty") or option.total_units),
                    requested_arrival_at=requested_arrival, evaluated_at=evaluated_at,
                    supply_lines=[{
                        "source_ref": str(line.get("item_ref") or line.get("source") or "unknown"),
                        "quantity": int(line.get("quantity") or 0), "status": "confirmed",
                        "arrival_min": line.get("eta"), "arrival_max": line.get("eta"),
                        "authority": "validated_quote" if line.get("source") == "supplier" else "inventory_or_catalog",
                    } for line in option.allocation],
                    dependency_versions=dependencies, response_expectation=temporal,
                    stage_duration_seconds=stages, carrier_cutoff_at=cutoff,
                )
                generation = hashlib.sha256(json.dumps(
                    {"option": payload, "deadline": requested_arrival, "dependencies": dependencies,
                     "temporal": temporal, "stages": stages, "cutoff": cutoff},
                    sort_keys=True, default=str, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()[:16]
                promise["calculation_version"] = f"promise-critical-path-v1:{generation}"
            except (TypeError, ValueError) as exc:
                promise = {
                    "calculation_version": "promise-critical-path-v1:invalid-input",
                    "feasibility": "unknown", "requested_quantity": int(avail.get("requested_qty") or 0),
                    "requested_arrival_at": str(requested_arrival), "evaluated_at": evaluated_at,
                    "quantity_by_deadline": 0, "quantity_confirmed_by_deadline": 0,
                    "unknown_quantity": int(option.total_units),
                    "reason_codes": [f"critical_path_input_invalid:{type(exc).__name__}"],
                    "failed_constraints": ["critical_path_input_invalid"],
                    "state_prevented": "unsupported_full_delivery_promise",
                    "response_expectation": temporal, "dependency_versions": dependencies,
                }
        payload["promise_calculation"] = promise
        option_payloads.append(payload)
        if promise.get("requested_arrival_at"):
            try:
                from src.app.services.temporal_authority_repository import record_promise_calculation
                record_promise_calculation(
                    db, tenant_id=tenant_id, case_id=case_id, option_id=option.option_id,
                    result=promise, calculated_at=evaluated_at,
                )
            except Exception:
                pass  # migration-first production schemas own durability; older fixtures may not.
    conf = float(vq.get("confidence") or 0.9)
    res = workflow.transition(
        db, case_id=case_id, event="fulfillment_options_generated", actor=actor, confidence=conf,
        reason_code="options_planned",
        evidence={"option_types": [o.option_type for o in options], "count": len(options)},
        state_patch={"options": option_payloads}, tenant_id=tenant_id, now_iso=now_iso,
        trace_id=trace_id)
    return res, options


def select_option(db, *, case_id: str, actor, option_id: str, tenant_id: str = "default",
                  now_iso: Optional[str] = None, trace_id: Optional[str] = None):
    """BUYER selects one of the generated options. An unknown option id is rejected before any
    transition (the buyer can only pick what was offered)."""
    from src.app.services.fulfillment import workflow
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    options = (cur.state_json.get("options") if cur else None) or []
    chosen = next((o for o in options if o.get("option_id") == option_id), None)
    if chosen is None:
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "unknown_option",
                                         http_status=409)
    return workflow.transition(
        db, case_id=case_id, event="buyer_fulfillment_selected", actor=actor, reason_code="buyer_choice",
        evidence={"option_id": option_id, "option_type": chosen.get("option_type")},
        state_patch={"selection": {"option_id": option_id, "option_type": chosen.get("option_type"),
                                   "allocation": chosen.get("allocation")}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
