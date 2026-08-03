"""Canonical disruption observations and bounded commercial impact projections.

External evidence remains advisory. A disruption can produce a proposal only
when a time-valid tenant dependency path connects an affected node to the
target. This module never changes allocations, prices, payments, orders,
messages, or buyer promises.
"""
from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy import inspect

from src.app.services.supply_graph_repository import bounded_dependency_paths


DISRUPTION_TYPES = frozenset({
    "port_congestion", "port_closure", "customs_hold", "customs_system_outage",
    "inspection_delay", "carrier_cancellation", "lane_weather_risk",
    "regulatory_restriction", "sanctions_match", "supplier_capacity_constraint",
    "quality_hold", "fuel_cost_change", "commodity_cost_change", "currency_change",
})
CLAIM_STATUSES = frozenset({
    "reported", "possible", "supported", "confirmed", "disproved", "resolved",
    "corrected", "retracted",
})
CONTRADICTION_STATUSES = frozenset({
    "unchallenged", "contested", "incomparable_scopes", "resolved",
})
SEVERITIES = frozenset({"low", "medium", "high", "critical"})


def _utc(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stamp(value: Any) -> str:
    return _utc(value).isoformat()


def _range(value: Any, *, minimum: float = 0, maximum: float | None = None) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("disruption_range_invalid")
    low, high = float(value[0]), float(value[1])
    if low < minimum or high < low or (maximum is not None and high > maximum):
        raise ValueError("disruption_range_invalid")
    return low, high


def record_disruption_observation(
    db,
    *,
    tenant_id: str,
    disruption_type: str,
    affected_node_ids: list[str],
    effective_from: str,
    observed_at: str,
    retrieved_at: str,
    fresh_until: str,
    source_id: str,
    source_record_id: str,
    source_revision: str,
    source_licence: str,
    evidence_ref: str,
    severity: str,
    probability_range: tuple[float, float],
    delay_range_days: tuple[int, int],
    cost_impact_range_minor: tuple[int, int],
    currency: str,
    claim_status: str,
    contradiction_status: str = "unchallenged",
    contradiction_group: str | None = None,
    geography: str | None = None,
    effective_to: str | None = None,
    published_at: str | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    event_type = str(disruption_type or "").strip()
    claim = str(claim_status or "").strip()
    contradiction = str(contradiction_status or "").strip()
    severity_value = str(severity or "").strip()
    nodes = sorted({str(node).strip() for node in affected_node_ids if str(node).strip()})
    if not tenant or not nodes or event_type not in DISRUPTION_TYPES:
        raise ValueError("disruption_scope_invalid")
    if claim not in CLAIM_STATUSES or contradiction not in CONTRADICTION_STATUSES:
        raise ValueError("disruption_evidence_status_invalid")
    if severity_value not in SEVERITIES:
        raise ValueError("disruption_severity_invalid")
    if not all((source_id, source_record_id, source_revision, source_licence, evidence_ref, currency)):
        raise ValueError("disruption_provenance_required")
    effective = _utc(effective_from)
    observed = _utc(observed_at)
    retrieved = _utc(retrieved_at)
    fresh = _utc(fresh_until)
    effective_end = _utc(effective_to) if effective_to else None
    if fresh < retrieved or (effective_end and effective_end < effective):
        raise ValueError("disruption_time_range_invalid")
    probability = _range(probability_range, maximum=1)
    delay = _range(delay_range_days)
    cost = _range(cost_impact_range_minor)
    node_query = text(
        "SELECT id FROM supply_node WHERE tenant_id=:tenant AND id IN :nodes "
        "AND recorded_to IS NULL"
    ).bindparams(bindparam("nodes", expanding=True))
    found = db.execute(node_query, {"tenant": tenant, "nodes": nodes}).fetchall()
    if {str(row[0]) for row in found} != set(nodes):
        raise ValueError("disruption_affected_node_invalid")
    existing = db.execute(text(
        "SELECT id FROM supply_disruption_observation WHERE tenant_id=:tenant "
        "AND source_id=:source AND source_record_id=:record AND source_revision=:revision"
    ), {"tenant": tenant, "source": source_id, "record": source_record_id,
        "revision": source_revision}).scalar()
    if existing:
        return {"id": str(existing), "tenant_id": tenant, "idempotent_replay": True,
                "authority": "advisory_only", "execution_allowed": False}
    observation_id = uuid.uuid4().hex
    recorded = datetime.now(timezone.utc).isoformat()
    previous = db.execute(text(
        "SELECT id FROM supply_disruption_observation WHERE tenant_id=:tenant "
        "AND source_id=:source AND source_record_id=:record AND recorded_to IS NULL "
        "ORDER BY recorded_at DESC LIMIT 1"
    ), {"tenant": tenant, "source": source_id, "record": source_record_id}).scalar()
    if previous:
        db.execute(text(
            "UPDATE supply_disruption_observation SET recorded_to=:recorded "
            "WHERE id=:id AND tenant_id=:tenant AND recorded_to IS NULL"
        ), {"recorded": recorded, "id": previous, "tenant": tenant})
    db.execute(text(
        "INSERT INTO supply_disruption_observation "
        "(id,tenant_id,disruption_type,affected_node_ids_json,geography,effective_from,"
        "effective_to,observed_at,retrieved_at,published_at,fresh_until,source_id,"
        "source_record_id,source_revision,source_licence,evidence_ref,severity,"
        "probability_low,probability_high,delay_low_days,delay_high_days,cost_low_minor,"
        "cost_high_minor,currency,contradiction_group,contradiction_status,claim_status,"
        "authority,recorded_at,recorded_to,supersedes_id) VALUES "
        "(:id,:tenant,:kind,:nodes,:geography,:effective_from,:effective_to,:observed_at,"
        ":retrieved_at,:published_at,:fresh_until,:source,:record,:revision,:licence,"
        ":evidence,:severity,:probability_low,:probability_high,:delay_low,:delay_high,"
        ":cost_low,:cost_high,:currency,:contradiction_group,:contradiction_status,"
        ":claim_status,'advisory_only',:recorded_at,NULL,:supersedes_id)"
    ), {"id": observation_id, "tenant": tenant, "kind": event_type,
        "nodes": json.dumps(nodes), "geography": geography,
        "effective_from": effective.isoformat(),
        "effective_to": effective_end.isoformat() if effective_end else None,
        "observed_at": observed.isoformat(), "retrieved_at": retrieved.isoformat(),
        "published_at": _stamp(published_at) if published_at else None,
        "fresh_until": fresh.isoformat(), "source": source_id, "record": source_record_id,
        "revision": source_revision, "licence": source_licence, "evidence": evidence_ref,
        "severity": severity_value, "probability_low": probability[0],
        "probability_high": probability[1], "delay_low": int(delay[0]),
        "delay_high": int(delay[1]), "cost_low": int(cost[0]), "cost_high": int(cost[1]),
        "currency": str(currency).upper(), "contradiction_group": contradiction_group,
        "contradiction_status": contradiction, "claim_status": claim,
        "recorded_at": recorded, "supersedes_id": previous})
    return {"id": observation_id, "tenant_id": tenant, "disruption_type": event_type,
            "affected_node_ids": nodes, "claim_status": claim,
            "contradiction_status": contradiction, "authority": "advisory_only",
            "execution_allowed": False, "external_action": "none",
            "supersedes_id": str(previous) if previous else None,
            "idempotent_replay": False}


def _no_impact(*, tenant_id: str, observation_id: str, target_node_id: str,
               reason: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "observation_id": observation_id,
            "target_node_id": target_node_id, "status": "no_commercial_change",
            "reason": reason, "dependency_path": None, "impact": None,
            "proposals": [], "authority": "proposal_only", "execution_allowed": False,
            "external_action": "none", "state_prevented": "commercial_state_mutation"}


def project_disruption_impact(
    db,
    *,
    tenant_id: str,
    observation_id: str,
    target_node_id: str,
    baseline_version: str,
    baseline: dict[str, Any],
    decision_time: str,
    persist: bool = True,
) -> dict[str, Any]:
    """Return a bounded proposal; never mutate commercial authority or state."""
    row = db.execute(text(
        "SELECT affected_node_ids_json,effective_from,effective_to,fresh_until,source_id,"
        "source_revision,source_licence,evidence_ref,severity,probability_low,probability_high,"
        "delay_low_days,delay_high_days,cost_low_minor,cost_high_minor,currency,"
        "contradiction_status,claim_status,recorded_to FROM supply_disruption_observation "
        "WHERE id=:id AND tenant_id=:tenant"
    ), {"id": observation_id, "tenant": tenant_id}).mappings().first()
    if row is None:
        raise KeyError("disruption_observation_not_found")
    at = _utc(decision_time)
    if row["recorded_to"] is not None:
        return _no_impact(tenant_id=tenant_id, observation_id=observation_id,
                          target_node_id=target_node_id, reason="observation_superseded")
    if row["claim_status"] in {"disproved", "resolved", "corrected", "retracted"}:
        return _no_impact(tenant_id=tenant_id, observation_id=observation_id,
                          target_node_id=target_node_id, reason="claim_not_active")
    if row["claim_status"] not in {"supported", "confirmed"}:
        return _no_impact(tenant_id=tenant_id, observation_id=observation_id,
                          target_node_id=target_node_id, reason="claim_not_corroborated")
    if row["contradiction_status"] in {"contested", "incomparable_scopes"}:
        return _no_impact(tenant_id=tenant_id, observation_id=observation_id,
                          target_node_id=target_node_id, reason="evidence_contested")
    effective_to = _utc(row["effective_to"]) if row["effective_to"] else None
    if at < _utc(row["effective_from"]) or at >= _utc(row["fresh_until"]) or (
        effective_to and at >= effective_to
    ):
        return _no_impact(tenant_id=tenant_id, observation_id=observation_id,
                          target_node_id=target_node_id, reason="observation_stale_or_inactive")
    selected_path = None
    for affected in json.loads(row["affected_node_ids_json"]):
        forward = bounded_dependency_paths(
            db, tenant_id=tenant_id, source_node_id=affected,
            target_node_id=target_node_id, at=at,
        )
        if forward["paths"]:
            selected_path = {"affected_node_id": affected, "orientation": "affected_to_target",
                             "edges": forward["paths"][0]}
            break
        reverse = bounded_dependency_paths(
            db, tenant_id=tenant_id, source_node_id=target_node_id,
            target_node_id=affected, at=at,
        )
        if reverse["paths"]:
            selected_path = {"affected_node_id": affected, "orientation": "target_to_affected",
                             "edges": reverse["paths"][0]}
            break
    if selected_path is None:
        return _no_impact(tenant_id=tenant_id, observation_id=observation_id,
                          target_node_id=target_node_id, reason="no_time_valid_dependency_path")
    baseline_currency = str(baseline.get("currency") or "").upper()
    if not baseline_currency or baseline_currency != str(row["currency"]).upper():
        return _no_impact(tenant_id=tenant_id, observation_id=observation_id,
                          target_node_id=target_node_id, reason="currency_not_comparable")
    quantity = max(1, int(baseline.get("quantity") or 1))
    price = max(0, int(baseline.get("unit_sell_price_minor") or 0))
    unit_cost = max(0, int(baseline.get("unit_landed_cost_minor") or 0))
    eta = _range(baseline.get("eta_days") or (0, 0))
    freight = _range(baseline.get("freight_cost_minor") or (0, 0))
    delay = (int(row["delay_low_days"]), int(row["delay_high_days"]))
    event_cost = (int(row["cost_low_minor"]), int(row["cost_high_minor"]))
    revised_freight = (int(freight[0]) + event_cost[0], int(freight[1]) + event_cost[1])
    revenue = quantity * price
    baseline_landed = quantity * unit_cost
    baseline_margin = (revenue - baseline_landed) / revenue if revenue else None
    revised_margin = (
        ((revenue - baseline_landed - event_cost[1]) / revenue,
         (revenue - baseline_landed - event_cost[0]) / revenue)
        if revenue else (None, None)
    )
    result = {
        "tenant_id": tenant_id, "observation_id": observation_id,
        "target_node_id": target_node_id, "baseline_version": baseline_version,
        "status": "bounded_recalculation_proposed", "dependency_path": selected_path,
        "evidence": {"source_id": row["source_id"], "source_revision": row["source_revision"],
                     "source_licence": row["source_licence"], "evidence_ref": row["evidence_ref"],
                     "claim_status": row["claim_status"], "severity": row["severity"],
                     "probability_range": {"low": row["probability_low"],
                                           "high": row["probability_high"]}},
        "impact": {
            "eta_days": {"before": {"low": int(eta[0]), "high": int(eta[1])},
                         "proposed": {"low": int(eta[0]) + delay[0],
                                      "high": int(eta[1]) + delay[1]}},
            "freight_cost_minor": {"currency": baseline_currency,
                                   "before": {"low": int(freight[0]), "high": int(freight[1])},
                                   "proposed": {"low": revised_freight[0],
                                                "high": revised_freight[1]}},
            "contribution_margin": {
                "before": round(baseline_margin, 6) if baseline_margin is not None else None,
                "proposed": {"low": round(revised_margin[0], 6) if revised_margin[0] is not None else None,
                             "high": round(revised_margin[1], 6) if revised_margin[1] is not None else None},
            },
        },
        "proposals": [
            {"type": "buyer_promise_review", "state": "proposed_not_applied",
             "eta_days": {"low": int(eta[0]) + delay[0], "high": int(eta[1]) + delay[1]}},
            {"type": "payment_authorization_review", "state": "review_required",
             "current_authorization_minor": int(baseline.get("payment_authorization_minor") or 0),
             "proposed_capture_minor": 0},
            {"type": "freight_or_supplier_recovery", "state": "human_review_required"},
        ],
        "authority": "proposal_only", "execution_allowed": False,
        "external_action": "none", "state_prevented": "commercial_state_mutation",
    }
    if persist:
        existing = db.execute(text(
            "SELECT id FROM supply_disruption_impact_projection WHERE tenant_id=:tenant "
            "AND observation_id=:observation AND target_node_id=:target "
            "AND baseline_version=:version"
        ), {"tenant": tenant_id, "observation": observation_id, "target": target_node_id,
            "version": baseline_version}).scalar()
        if existing:
            result["projection_id"] = str(existing)
            result["idempotent_replay"] = True
        else:
            projection_id = uuid.uuid4().hex
            db.execute(text(
                "INSERT INTO supply_disruption_impact_projection "
                "(id,tenant_id,observation_id,target_node_id,baseline_version,dependency_path_json,"
                "projection_json,status,authority,created_at) VALUES "
                "(:id,:tenant,:observation,:target,:version,:path,:projection,:status,"
                "'proposal_only',:created_at)"
            ), {"id": projection_id, "tenant": tenant_id, "observation": observation_id,
                "target": target_node_id, "version": baseline_version,
                "path": json.dumps(selected_path, sort_keys=True),
                "projection": json.dumps(result, sort_keys=True), "status": result["status"],
                "created_at": datetime.now(timezone.utc).isoformat()})
            result["projection_id"] = projection_id
            result["idempotent_replay"] = False
    return result


def disruption_workbench_projection(
    db, *, tenant_id: str, sku: str | None = None, limit: int = 25,
) -> list[dict[str, Any]]:
    """Return tenant-owned, already-persisted advisory projections for operator UX.

    SKU filtering is exact against canonical product/variant logical keys.  The
    projector never infers exposure from product text and never recalculates or
    mutates commercial state while serving a read model.
    """
    # Inspect through the session connection so in-memory SQLite tests and an
    # active transaction are not disturbed by a second engine checkout.
    inspector = inspect(db.connection())
    required = {
        "supply_disruption_observation", "supply_disruption_impact_projection",
        "supply_node",
    }
    if not required.issubset(set(inspector.get_table_names())):
        return []
    params: dict[str, Any] = {
        "tenant": str(tenant_id), "limit": max(1, min(int(limit), 100)),
    }
    sku_filter = ""
    if sku:
        canonical = str(sku).strip()
        params.update({
            "sku": canonical, "variant": f"variant:{canonical}",
            "product": f"product:{canonical}",
        })
        sku_filter = " AND n.logical_key IN (:sku,:variant,:product)"
    rows = db.execute(text(
        "SELECT p.id,p.observation_id,p.baseline_version,p.projection_json,p.status,"
        "p.authority,p.created_at,o.disruption_type,o.geography,o.effective_from,"
        "o.effective_to,o.observed_at,o.retrieved_at,o.fresh_until,o.source_id,"
        "o.source_revision,o.source_licence,o.evidence_ref,o.severity,o.claim_status,"
        "o.contradiction_status,n.logical_key "
        "FROM supply_disruption_impact_projection p "
        "JOIN supply_disruption_observation o ON o.id=p.observation_id "
        "JOIN supply_node n ON n.id=p.target_node_id AND n.tenant_id=p.tenant_id "
        "WHERE p.tenant_id=:tenant AND o.tenant_id=:tenant AND o.recorded_to IS NULL "
        "AND n.recorded_to IS NULL" + sku_filter +
        " ORDER BY p.created_at DESC LIMIT :limit"
    ), params).mappings().all()
    projected: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["projection_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        payload.update({
            "projection_id": str(row["id"]),
            "observation_id": str(row["observation_id"]),
            "baseline_version": str(row["baseline_version"]),
            "status": str(row["status"]),
            "authority": str(row["authority"]),
            "disruption_type": str(row["disruption_type"]),
            "target_logical_key": str(row["logical_key"]),
            "geography": row["geography"],
            "effective_from": row["effective_from"],
            "effective_to": row["effective_to"],
            "observed_at": row["observed_at"],
            "retrieved_at": row["retrieved_at"],
            "fresh_until": row["fresh_until"],
            "claim_status": str(row["claim_status"]),
            "contradiction_status": str(row["contradiction_status"]),
            "severity": str(row["severity"]),
            "freshness": (
                "current" if _utc(row["fresh_until"]) > datetime.now(timezone.utc)
                else "stale"
            ),
            "created_at": row["created_at"],
        })
        evidence = dict(payload.get("evidence") or {})
        evidence.update({
            "source_id": str(row["source_id"]),
            "source_revision": str(row["source_revision"]),
            "source_licence": str(row["source_licence"]),
            "evidence_ref": str(row["evidence_ref"]),
            "severity": str(row["severity"]),
            "claim_status": str(row["claim_status"]),
        })
        payload["evidence"] = evidence
        projected.append(payload)
    return projected


def draft_disruption_buyer_reviews(
    db, *, tenant_id: str, projection_id: str,
) -> dict[str, Any]:
    """Draft truthful, case-scoped buyer reviews from a persisted proposal.

    Only committed demand is eligible. The resulting communication lifecycle
    starts at ``proposed``; this function cannot approve, queue, deliver, amend
    a promise, capture payment, or expose another buyer's identity.
    """
    row = db.execute(text(
        "SELECT p.projection_json,p.status,p.authority,p.observation_id,n.logical_key "
        "FROM supply_disruption_impact_projection p JOIN supply_node n "
        "ON n.id=p.target_node_id AND n.tenant_id=p.tenant_id "
        "WHERE p.id=:id AND p.tenant_id=:tenant"
    ), {"id": str(projection_id), "tenant": str(tenant_id)}).fetchone()
    if row is None:
        raise KeyError("disruption_projection_not_found")
    if str(row[1]) != "bounded_recalculation_proposed" or str(row[2]) != "proposal_only":
        return {
            "status": "blocked",
            "reason": "projection_not_eligible",
            "draft_count": 0,
            "auto_sent": False,
            "human_authorization_required": True,
        }
    try:
        projection = json.loads(str(row[0] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("disruption_projection_malformed") from exc
    eta = (((projection.get("impact") or {}).get("eta_days") or {}).get("proposed") or {})
    if eta.get("low") is None or eta.get("high") is None:
        raise ValueError("disruption_projection_eta_required")
    logical_key = str(row[4] or "")
    sku = logical_key.split(":", 1)[1] if ":" in logical_key else logical_key
    demands = db.execute(text(
        "SELECT id,case_id,quantity FROM demand_commitment WHERE tenant_id=:tenant "
        "AND sku=:sku AND stage='committed' ORDER BY case_id,id"
    ), {"tenant": str(tenant_id), "sku": sku}).fetchall()
    from src.app.services.communication_observations import record_message_observation

    drafts = []
    evidence = projection.get("evidence") or {}
    for demand in demands:
        demand_id, case_id, quantity = str(demand[0]), str(demand[1]), int(demand[2])
        identity = "|".join((str(tenant_id), str(projection_id), demand_id, case_id))
        message_id = "disruption-review:" + hashlib.sha256(identity.encode()).hexdigest()
        payload = {
            "template_id": "buyer-disruption-review-v1",
            "case_id": case_id,
            "sku": sku,
            "quantity": quantity,
            "revised_eta_days": {"low": int(eta["low"]), "high": int(eta["high"])},
            "wording": (
                "A verified supply-chain observation may affect the delivery window. "
                f"The current review range is {int(eta['low'])}-{int(eta['high'])} days. "
                "No revised promise or payment change has been applied; an operator must review it."
            ),
            "claim_status": evidence.get("claim_status"),
            "source_id": evidence.get("source_id"),
            "source_revision": evidence.get("source_revision"),
            "projection_id": str(projection_id),
            "human_authorization_required": True,
            "auto_sent": False,
        }
        result = record_message_observation(
            db=db,
            tenant_id=str(tenant_id),
            party_type="buyer",
            direction="outbound",
            channel="internal_draft",
            provider_message_id=message_id,
            purpose="delivery_disruption_review",
            consent_status="not_required",
            security_status="clean",
            sanitized_payload=payload,
            case_ref=case_id,
            evidence_ref=f"disruption_projection:{projection_id}",
        )
        drafts.append({"case_id": case_id, "demand_id": demand_id, **result})
    return {
        "status": "drafted_for_human_review" if drafts else "no_committed_demand",
        "projection_id": str(projection_id),
        "draft_count": len(drafts),
        "drafts": drafts,
        "auto_sent": False,
        "human_authorization_required": True,
        "state_prevented": ["buyer_promise_mutation", "payment_change", "message_delivery"],
    }
