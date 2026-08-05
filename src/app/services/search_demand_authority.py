"""Tenant-scoped search-to-demand authority ledger.

Raw searches are interest observations, never inventory demand.  Authority increases
only through explicit lifecycle events.  This module is deliberately product-agnostic:
requirements are opaque, versioned JSON and product identity is an optional canonical SKU.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text


STAGE_AUTHORITY = {
    "search_interest": "interest",
    "clarification_requested": "interest",
    "qualified_interest": "qualified",
    "product_viewed": "qualified",
    "provisional_cart": "provisional",
    "buyer_commitment": "committed",
    "allocation": "committed",
    "order": "ordered",
    "fulfilled": "fulfilled",
    "return": "outcome",
    "cancellation": "outcome",
}

QUALIFICATION_OUTCOMES = {
    "exact", "qualified", "alternative", "no_match", "blocked", "unresolved",
}

_AUTHORITY_RANK = {
    "interest": 0, "qualified": 1, "provisional": 2, "committed": 3,
    "ordered": 4, "fulfilled": 5, "outcome": 6,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value if isinstance(value, (dict, list)) else {}, sort_keys=True,
                      separators=(",", ":"), default=str)


def _hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def requirement_fingerprint(requirement: dict[str, Any]) -> str:
    return _hash(_canonical_json(requirement))[:32]


def _validated_inventory_snapshot(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {"status": "not_recorded"}
    required = {"source_version", "observed_at", "freshness_status"}
    if not required <= set(value):
        return {"status": "incomplete", "missing": sorted(required - set(value))}
    out = {
        "status": "recorded",
        "source_version": str(value.get("source_version") or "")[:160],
        "observed_at": str(value.get("observed_at") or "")[:80],
        "freshness_status": str(value.get("freshness_status") or "unknown")[:40],
    }
    for key in ("confirmed_atp", "transferable", "unconfirmed_shortfall"):
        raw = value.get(key)
        out[key] = max(0, int(raw or 0)) if raw is not None else None
    return out


def append_search_observation(
    db,
    *,
    tenant_id: str,
    trace_id: str,
    session_epoch: str,
    actor_hash: str,
    query: str,
    requirement: dict[str, Any],
    qualification_outcome: str,
    lifecycle_stage: str,
    case_id: str | None = None,
    resolved_sku: str | None = None,
    unresolved_concept: str | None = None,
    requested_quantity: int | None = None,
    evidence_refs: Iterable[str] = (),
    source_policy_status: str = "not_evaluated",
    actor_dedup_class: str = "distinct_actor",
    abuse_status: str = "not_evaluated",
    authority: str | None = None,
    inventory_snapshot: dict[str, Any] | None = None,
    observed_at: str | None = None,
    effective_at: str | None = None,
    supersedes_id: str | None = None,
    simulation_only: bool = False,
) -> dict[str, Any]:
    """Append one observation. The lifecycle deterministically owns authority."""
    tenant = str(tenant_id or "").strip()
    trace = str(trace_id or "").strip()
    epoch = str(session_epoch or "").strip()
    actor = str(actor_hash or "").strip()
    if not all((tenant, trace, epoch, actor)):
        raise ValueError("tenant_trace_session_actor_required")
    stage = str(lifecycle_stage or "").strip()
    if stage not in STAGE_AUTHORITY:
        raise ValueError("unsupported_search_lifecycle_stage")
    outcome = str(qualification_outcome or "").strip()
    if outcome not in QUALIFICATION_OUTCOMES:
        raise ValueError("unsupported_qualification_outcome")
    canonical_authority = STAGE_AUTHORITY[stage]
    # Caller-provided authority is advisory only. A search event cannot self-promote.
    _ = authority
    quantity = None if requested_quantity is None else max(0, int(requested_quantity))
    observed = str(observed_at or _now())
    effective = str(effective_at or observed)
    snapshot = _validated_inventory_snapshot(inventory_snapshot)
    refs = sorted({str(item).strip()[:200] for item in evidence_refs if str(item).strip()})[:24]
    row = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant,
        "trace_id": trace,
        "case_id": str(case_id or "").strip() or None,
        "session_epoch": epoch,
        "actor_hash": actor,
        "actor_dedup_class": str(actor_dedup_class or "not_evaluated")[:40],
        "abuse_status": str(abuse_status or "not_evaluated")[:40],
        "requirement_fingerprint": requirement_fingerprint(requirement),
        "query_hash": _hash(query),
        "resolved_sku": str(resolved_sku or "").strip()[:192] or None,
        "unresolved_concept": str(unresolved_concept or "").strip()[:240] or None,
        "requested_quantity": quantity,
        "qualification_outcome": outcome,
        "evidence_refs_json": json.dumps(refs),
        "source_policy_status": str(source_policy_status or "not_evaluated")[:80],
        "lifecycle_stage": stage,
        "authority": canonical_authority,
        "inventory_snapshot_json": json.dumps(snapshot, sort_keys=True),
        "observed_at": observed,
        "effective_at": effective,
        "supersedes_id": str(supersedes_id or "").strip() or None,
        "simulation_only": bool(simulation_only),
        "created_at": _now(),
    }
    db.execute(text("""
        INSERT INTO search_demand_observation (
          id, tenant_id, trace_id, case_id, session_epoch, actor_hash,
          actor_dedup_class, abuse_status, requirement_fingerprint, query_hash,
          resolved_sku, unresolved_concept, requested_quantity, qualification_outcome,
          evidence_refs_json, source_policy_status, lifecycle_stage, authority,
          inventory_snapshot_json, observed_at, effective_at, supersedes_id,
          simulation_only, created_at
        ) VALUES (
          :id, :tenant_id, :trace_id, :case_id, :session_epoch, :actor_hash,
          :actor_dedup_class, :abuse_status, :requirement_fingerprint, :query_hash,
          :resolved_sku, :unresolved_concept, :requested_quantity, :qualification_outcome,
          :evidence_refs_json, :source_policy_status, :lifecycle_stage, :authority,
          :inventory_snapshot_json, :observed_at, :effective_at, :supersedes_id,
          :simulation_only, :created_at
        )
    """), row)
    return dict(row)


def append_lifecycle_transition(
    db,
    *,
    tenant_id: str,
    lifecycle_stage: str,
    case_id: str | None = None,
    trace_id: str | None = None,
    requested_quantity: int | None = None,
    resolved_sku: str | None = None,
    inventory_snapshot: dict[str, Any] | None = None,
    observed_at: str | None = None,
    simulation_only: bool | None = None,
) -> dict[str, Any]:
    """Advance an existing search subject without reconstructing its identity from prose.

    The prior observation supplies the tenant/session/actor/requirement/evidence identity.
    If no prior subject exists, the caller receives a typed ``not_linked`` result rather
    than a synthetic lifecycle record that would corrupt funnel attribution.
    """
    stage = str(lifecycle_stage or "").strip()
    if stage not in STAGE_AUTHORITY:
        raise ValueError("unsupported_search_lifecycle_stage")
    tenant = str(tenant_id or "").strip()
    case = str(case_id or "").strip()
    trace = str(trace_id or "").strip()
    if not tenant or not (case or trace):
        raise ValueError("tenant_and_case_or_trace_required")
    predicates = []
    params: dict[str, Any] = {"tenant": tenant}
    if case:
        predicates.append("case_id=:case_id")
        params["case_id"] = case
    if trace:
        predicates.append("trace_id=:trace_id")
        params["trace_id"] = trace
    prior = db.execute(text(
        "SELECT id,trace_id,case_id,session_epoch,actor_hash,actor_dedup_class,"
        "abuse_status,requirement_fingerprint,query_hash,resolved_sku,unresolved_concept,"
        "requested_quantity,qualification_outcome,evidence_refs_json,source_policy_status,"
        "inventory_snapshot_json,simulation_only FROM search_demand_observation "
        "WHERE tenant_id=:tenant AND (" + " OR ".join(predicates) + ") "
        "ORDER BY created_at DESC,id DESC LIMIT 1"
    ), params).mappings().first()
    if prior is None:
        return {
            "status": "not_linked",
            "state_prevented": "lifecycle_attribution_without_prior_search_identity",
            "lifecycle_stage": stage,
        }

    now = str(observed_at or _now())
    row = dict(prior)
    row.update({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant,
        "trace_id": trace or str(prior["trace_id"]),
        "case_id": case or str(prior.get("case_id") or "") or None,
        "resolved_sku": str(resolved_sku or prior.get("resolved_sku") or "").strip() or None,
        "requested_quantity": (
            max(0, int(requested_quantity))
            if requested_quantity is not None else prior.get("requested_quantity")
        ),
        "lifecycle_stage": stage,
        "authority": STAGE_AUTHORITY[stage],
        "inventory_snapshot_json": (
            json.dumps(_validated_inventory_snapshot(inventory_snapshot), sort_keys=True)
            if inventory_snapshot is not None else str(prior["inventory_snapshot_json"])
        ),
        "observed_at": now,
        "effective_at": now,
        "supersedes_id": str(prior["id"]),
        "simulation_only": (
            bool(simulation_only) if simulation_only is not None else bool(prior["simulation_only"])
        ),
        "created_at": _now(),
    })
    db.execute(text("""
        INSERT INTO search_demand_observation (
          id, tenant_id, trace_id, case_id, session_epoch, actor_hash,
          actor_dedup_class, abuse_status, requirement_fingerprint, query_hash,
          resolved_sku, unresolved_concept, requested_quantity, qualification_outcome,
          evidence_refs_json, source_policy_status, lifecycle_stage, authority,
          inventory_snapshot_json, observed_at, effective_at, supersedes_id,
          simulation_only, created_at
        ) VALUES (
          :id, :tenant_id, :trace_id, :case_id, :session_epoch, :actor_hash,
          :actor_dedup_class, :abuse_status, :requirement_fingerprint, :query_hash,
          :resolved_sku, :unresolved_concept, :requested_quantity, :qualification_outcome,
          :evidence_refs_json, :source_policy_status, :lifecycle_stage, :authority,
          :inventory_snapshot_json, :observed_at, :effective_at, :supersedes_id,
          :simulation_only, :created_at
        )
    """), row)
    return {"status": "appended", **row}


def _all_rows(db, *, tenant_id: str) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT id, trace_id, case_id, session_epoch, actor_hash, actor_dedup_class,
               abuse_status, requirement_fingerprint, resolved_sku, unresolved_concept,
               requested_quantity, qualification_outcome, lifecycle_stage, authority,
               inventory_snapshot_json, source_policy_status, simulation_only,
               observed_at, effective_at, supersedes_id
        FROM search_demand_observation
        WHERE tenant_id=:tenant
        ORDER BY created_at ASC, id ASC
    """), {"tenant": str(tenant_id)}).mappings().all()
    return [dict(row) for row in rows]


def _active_rows(db, *, tenant_id: str) -> list[dict[str, Any]]:
    rows = _all_rows(db, tenant_id=tenant_id)
    superseded = {str(row["supersedes_id"]) for row in rows if row["supersedes_id"]}
    return [row for row in rows if str(row["id"]) not in superseded]


def _subject_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("case_id") or row.get("trace_id") or ""),
        str(row.get("session_epoch") or ""),
        str(row.get("requirement_fingerprint") or ""),
    )


def _latest_rows(db, *, tenant_id: str) -> list[dict[str, Any]]:
    by_subject: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _active_rows(db, tenant_id=tenant_id):
        key = (
            str(row.get("case_id") or row.get("trace_id") or ""),
            str(row.get("session_epoch") or ""),
            str(row.get("requirement_fingerprint") or ""),
        )
        previous = by_subject.get(key)
        if previous is None or _AUTHORITY_RANK.get(str(row["authority"]), -1) >= _AUTHORITY_RANK.get(
            str(previous["authority"]), -1
        ):
            by_subject[key] = row
    return list(by_subject.values())


def project_search_demand_authority(db, *, tenant_id: str) -> dict[str, Any]:
    """Operator projection. Interest stays separate from committed operational demand."""
    # Supersession changes the current projection; it must not rewrite the audit history.
    history = _all_rows(db, tenant_id=tenant_id)
    rows = _latest_rows(db, tenant_id=tenant_id)
    reached: dict[tuple[str, str, str], set[str]] = {}
    for row in history:
        reached.setdefault(_subject_key(row), set()).add(str(row["lifecycle_stage"]))
    reached_qualified = {
        key for key, stages in reached.items()
        if stages & {"qualified_interest", "product_viewed", "provisional_cart", "buyer_commitment",
                     "allocation", "order", "fulfilled"}
    }
    reached_cart = {key for key, stages in reached.items() if "provisional_cart" in stages}
    reached_commitment = {
        key for key, stages in reached.items()
        if stages & {"buyer_commitment", "allocation", "order", "fulfilled"}
    }
    reached_order = {key for key, stages in reached.items() if stages & {"order", "fulfilled"}}
    reached_fulfilled = {key for key, stages in reached.items() if "fulfilled" in stages}
    reached_return = {key for key, stages in reached.items() if "return" in stages}
    reached_cancellation = {key for key, stages in reached.items() if "cancellation" in stages}
    qualified = [
        row for row in rows
        if str(row["lifecycle_stage"]) in {
            "qualified_interest", "product_viewed", "provisional_cart", "buyer_commitment",
            "allocation", "order", "fulfilled",
        }
    ]
    provisional = [row for row in rows if str(row["authority"]) == "provisional"]
    committed = [
        row for row in rows
        if str(row["lifecycle_stage"]) in {"buyer_commitment", "allocation", "order", "fulfilled"}
    ]
    ordered = [row for row in rows if str(row["lifecycle_stage"]) in {"order", "fulfilled"}]
    fulfilled = [row for row in rows if str(row["authority"]) == "fulfilled"]
    unresolved = [row for row in rows if row.get("unresolved_concept") or row["qualification_outcome"] in {"blocked", "unresolved"}]
    no_match = [row for row in rows if row["qualification_outcome"] == "no_match"]
    eligible = [
        row for row in qualified
        if str(row.get("abuse_status")) not in {"review_required", "blocked"}
        and str(row.get("actor_dedup_class")) != "repeated_actor"
        and str(row.get("source_policy_status")) == "approved"
    ]
    confirmed_atp = transferable = snapshot_shortfall = 0
    versions: set[str] = set()
    freshness: set[str] = set()
    for row in committed:
        try:
            snapshot = json.loads(str(row.get("inventory_snapshot_json") or "{}"))
        except json.JSONDecodeError:
            snapshot = {}
        if snapshot.get("status") != "recorded":
            continue
        confirmed_atp += int(snapshot.get("confirmed_atp") or 0)
        transferable += int(snapshot.get("transferable") or 0)
        snapshot_shortfall += int(snapshot.get("unconfirmed_shortfall") or 0)
        if snapshot.get("source_version"):
            versions.add(str(snapshot["source_version"]))
        freshness.add(str(snapshot.get("freshness_status") or "unknown"))
    committed_units = sum(int(row.get("requested_quantity") or 0) for row in committed)
    denominator = len(rows)
    qualified_count = len(qualified)
    return {
        "tenant_id": str(tenant_id),
        "search_interest_count": denominator,
        "qualified_searches": qualified_count,
        "unresolved_concept_count": len(unresolved),
        "unresolved_concept_rate": round(len(unresolved) / denominator, 4) if denominator else None,
        "no_qualified_match_count": len(no_match),
        "no_qualified_match_rate": round(len(no_match) / denominator, 4) if denominator else None,
        "provisional_cart_count": len(provisional),
        "cart_reached_count": len(reached_cart),
        "committed_case_count": len(committed),
        "commitment_reached_count": len(reached_commitment),
        "ordered_case_count": len(ordered),
        "order_reached_count": len(reached_order),
        "fulfilled_case_count": len(fulfilled),
        "fulfilment_reached_count": len(reached_fulfilled),
        "return_reached_count": len(reached_return),
        "cancellation_reached_count": len(reached_cancellation),
        "qualified_to_cart_rate": round(len(reached_cart) / len(reached_qualified), 4) if reached_qualified else None,
        "cart_to_commitment_rate": round(len(reached_commitment) / len(reached_cart), 4) if reached_cart else None,
        "qualified_interest_units": sum(int(row.get("requested_quantity") or 0) for row in qualified),
        "committed_demand_units": committed_units,
        "confirmed_atp_units": confirmed_atp,
        "transferable_units": transferable,
        "qualified_unmet_units": snapshot_shortfall,
        "supplier_enquiry_pressure_units": snapshot_shortfall,
        "inventory_source_versions": sorted(versions),
        "inventory_freshness_states": sorted(freshness),
        "eligible_forecast_signal_count": len(eligible),
        "forecast_influence": "shadow_only",
        "baseline_forecast_basis": "authoritative_orders_fulfilments_and_lost_demand",
        "challenger_forecast_basis": "baseline_plus_qualified_search_signals",
        "forecast_comparison_status": "insufficient_sealed_outcomes",
        "projected_revenue": None,
        "projected_revenue_status": "undefined_without_order_or_approved_value_basis",
        "inventory_action_allowed": False,
        "authority_note": "raw searches are interest; only committed and ordered stages affect operations",
        "simulation_only": bool(rows) and all(bool(row.get("simulation_only")) for row in rows),
        "observation_authority": (
            "no_observations" if not rows
            else "simulation" if all(bool(row.get("simulation_only")) for row in rows)
            else "live_or_mixed"
        ),
        "as_of": _now(),
    }
