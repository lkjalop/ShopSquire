"""Held-out certification for live-model conversational case intake."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from typing import Any, Callable

from src.app.services.procurement_case_state import (
    CasePatch,
    ProcurementCaseState,
    apply_case_patch_set,
    resolve_temporal_constraint,
)
from src.app.services.recommendation_core import router_prompt
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import (
    TurnDecision,
    last_router_call_metrics,
    route_turn,
)


TURN_ONE = (
    "Equip our Brisbane lab with 37 engineering laptops for game engine development and "
    "engineering simulation. Cap total spend at AUD 185,000. Deliver 22 to Brisbane and "
    "15 to Adelaide within five days."
)
TURN_TWO = (
    "Move 3 units from Adelaide to Brisbane. Keep the quantity, budget, workloads, and "
    "deadline unchanged."
)
INTERPRETATION_INSTANT = datetime(2026, 8, 24, tzinfo=timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _receipts(decision: TurnDecision) -> list[dict[str, Any]]:
    rows = decision.model_proposal.get("case_patch_rejections") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _apply(state: ProcurementCaseState, decision: TurnDecision) -> ProcurementCaseState:
    return apply_case_patch_set(
        state,
        expected_revision=state.revision,
        patches=[CasePatch.model_validate(row) for row in decision.case_patches],
    ).state


def run_live_router_intake_certificate(
    db: Any,
    *,
    router: Callable[..., TurnDecision] = route_turn,
    metrics_reader: Callable[[], dict[str, Any]] = last_router_call_metrics,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Execute two held-out utterances through the real router and seal the projection.

    Supplying alternate callables is a unit-test seam. A passing live certificate still
    requires both provider receipts to identify Ollama and report ``outcome=ok``.
    """

    first_envelope = TurnEnvelope.from_suggest_params(
        query=TURN_ONE,
        buyer_query=TURN_ONE,
        uid="live-router-intake-certificate",
        tenant_id="default",
        currency="AUD",
        trace_id="live-router-intake-turn-1",
    )
    first = router(db, first_envelope, timeout=timeout_s)
    first_metrics = dict(metrics_reader())
    initial = ProcurementCaseState(case_id="held-out-router-37")
    first_state = _apply(initial, first)
    if first_state.temporal is not None:
        first_state = first_state.model_copy(update={
            "temporal": resolve_temporal_constraint(
                first_state.temporal,
                interpretation_instant=INTERPRETATION_INSTANT,
            ),
        })

    session = {
        "procurement_case_state": first_state.model_dump(mode="json"),
        "prior_node": first.node_handle,
        "active_workflow_lane": "PROCUREMENT",
        "accepted_constraints": {
            "quantity": first_state.requested_quantity,
            "budget_scope": first_state.budget.scope if first_state.budget else None,
            "total_budget_cents": first_state.budget.amount_minor if first_state.budget else None,
        },
        "session_epoch": first_state.case_id,
    }
    second_envelope = TurnEnvelope.from_suggest_params(
        query=TURN_TWO,
        buyer_query=TURN_TWO,
        uid="live-router-intake-certificate",
        tenant_id="default",
        currency="AUD",
        trace_id="live-router-intake-turn-2",
        session=session,
    )
    second = router(db, second_envelope, timeout=timeout_s)
    second_metrics = dict(metrics_reader())
    final_state = _apply(first_state, second)

    prompt_source = inspect.getsource(router_prompt)
    rejection_receipts = [*_receipts(first), *_receipts(second)]
    receipt_complete = all(
        row.get("schema_version") == "case_patch_rejection.v1"
        and bool(row.get("reason"))
        and bool(row.get("rejecting_predicate"))
        and isinstance(row.get("patch_index"), int)
        for row in rejection_receipts
    )
    metrics = [first_metrics, second_metrics]
    expected_temporal = first_state.temporal
    invariant_checks = {
        "held_out_turn_one_absent_from_router_prompt": TURN_ONE not in prompt_source,
        "held_out_turn_two_absent_from_router_prompt": TURN_TWO not in prompt_source,
        "both_turns_used_live_model": all(
            row.get("provider") == "ollama" and row.get("outcome") == "ok"
            for row in metrics
        ),
        "model_artifact_identity_recorded": all(
            bool(row.get("model")) and bool(row.get("model_version"))
            and len(str(row.get("model_artifact_digest") or "")) == 64
            for row in metrics
        ),
        "router_latency_recorded": all(float(row.get("wall_ms") or 0) > 0 for row in metrics),
        "quantity_extracted": first_state.requested_quantity == 37,
        "total_budget_extracted": bool(
            first_state.budget
            and first_state.budget.amount_minor == 18_500_000
            and first_state.budget.currency == "AUD"
            and first_state.budget.scope == "total"
        ),
        "workloads_extracted": set(first_state.workloads) == {
            "game_development", "engineering_simulation",
        },
        "destinations_extracted": {
            row.location_ref: row.quantity for row in first_state.destinations
        } == {"Brisbane": 22, "Adelaide": 15},
        "temporal_expression_retained": bool(
            expected_temporal and expected_temporal.original_expression == "within five days"
        ),
        "deadline_resolved_with_authority": bool(
            expected_temporal
            and expected_temporal.resolution_status == "resolved"
            and expected_temporal.resolved_utc_instant
            and expected_temporal.interpretation_instant
            and expected_temporal.calendar_source
            and expected_temporal.calendar_version
        ),
        "amendment_applied": {
            row.location_ref: row.quantity for row in final_state.destinations
        } == {"Brisbane": 25, "Adelaide": 12},
        "retained_fields_not_rewritten_by_amendment": all((
            final_state.requested_quantity == first_state.requested_quantity,
            final_state.budget == first_state.budget,
            final_state.workloads == first_state.workloads,
            final_state.temporal == first_state.temporal,
            {row.get("path") for row in second.case_patches} == {"destinations"},
        )),
        "case_revision_bound_to_each_turn": (
            first_state.revision == 2 and final_state.revision == 3
        ),
        "all_rejections_have_reason_and_predicate": receipt_complete,
        "no_commerce_authority_granted": not any(
            token in set(first.authorization_changes) | set(second.authorization_changes)
            for token in ("cart_mutation", "supplier_send", "payment", "reservation")
        ),
    }
    failures = [name for name, passed in invariant_checks.items() if not passed]
    artifact: dict[str, Any] = {
        "schema_version": "live-router-intake-certificate.v1",
        "certification_status": "passed" if not failures else "failed",
        "gate_failures": failures,
        "execution_mode": "live_local_model",
        "synthetic_scenario": True,
        "external_network_certified": False,
        "interpretation_instant": INTERPRETATION_INSTANT.isoformat(),
        "scenario": {"turn_one": TURN_ONE, "turn_two": TURN_TWO},
        "scenario_hash": _digest([TURN_ONE, TURN_TWO]),
        "router_executions": metrics,
        "turns": [
            {
                "turn": 1,
                "decision": first.as_dict(),
                "canonical_case": first_state.model_dump(mode="json"),
                "rejected_patches": _receipts(first),
            },
            {
                "turn": 2,
                "decision": second.as_dict(),
                "canonical_case": final_state.model_dump(mode="json"),
                "rejected_patches": _receipts(second),
            },
        ],
        "rejected_patch_count": len(rejection_receipts),
        "invariant_checks": invariant_checks,
        "authority_statement": (
            "This certificate proves live local-model intake into canonical case state; "
            "it grants no network, cart, supplier, payment, reservation, or purchase authority."
        ),
    }
    artifact["seal_sha256"] = _digest(artifact)
    return artifact


__all__ = [
    "INTERPRETATION_INSTANT", "TURN_ONE", "TURN_TWO",
    "run_live_router_intake_certificate",
]
