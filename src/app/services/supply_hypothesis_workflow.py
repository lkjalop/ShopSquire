"""Persisted, evidence-sealed and proposal-only supply hypothesis workflow."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text

from src.app.services.supply_impact_reasoner import (
    build_grounded_impact_hypothesis,
    propose_procurement_options,
)


SUPPLIER_OBSERVATION_TYPES = frozenset(
    {"confirmation", "contradiction", "narrowing"}
)
KNOWN_EXPOSURE_FIELDS = frozenset(
    {"current_atp", "incoming_supply", "revenue_at_risk", "open_commitments"}
)


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _load_graph(db, *, tenant_id: str, target_node_id: str, decision_time: datetime):
    target = db.execute(
        text(
            """
            SELECT id,node_type,logical_key,label,attributes_json,identity_status,
                   evidence_status,simulation_only,source_system,source_record_id,
                   provenance_json,valid_from,valid_to,recorded_from,recorded_to
            FROM supply_node
            WHERE tenant_id=:tenant AND id=:target
              AND identity_status='resolved'
              AND valid_from<=:at AND (valid_to IS NULL OR valid_to>:at)
              AND (recorded_from IS NULL OR recorded_from<=:at)
              AND (recorded_to IS NULL OR recorded_to>:at)
            """
        ),
        {
            "tenant": tenant_id,
            "target": target_node_id,
            "at": decision_time,
        },
    ).mappings().first()
    if not target:
        return None, [], []
    nodes = db.execute(
        text(
            """
            SELECT id,node_type,logical_key,label,attributes_json,identity_status,
                   evidence_status,simulation_only,source_system,source_record_id,
                   provenance_json,valid_from,valid_to,recorded_from,recorded_to
            FROM supply_node
            WHERE tenant_id=:tenant
              AND identity_status='resolved'
              AND valid_from<=:at AND (valid_to IS NULL OR valid_to>:at)
              AND (recorded_from IS NULL OR recorded_from<=:at)
              AND (recorded_to IS NULL OR recorded_to>:at)
            ORDER BY id LIMIT 5000
            """
        ),
        {"tenant": tenant_id, "at": decision_time},
    ).mappings().all()
    edges = db.execute(
        text(
            """
            SELECT id,from_node_id,to_node_id,relationship_type,properties_json,
                   confidence,evidence_status,simulation_only,source_system,
                   source_record_id,provenance_json,valid_from,valid_to,
                   recorded_from,recorded_to
            FROM supply_dependency_edge
            WHERE tenant_id=:tenant
              AND evidence_status IN ('observed','approved')
              AND valid_from<=:at AND (valid_to IS NULL OR valid_to>:at)
              AND (recorded_from IS NULL OR recorded_from<=:at)
              AND (recorded_to IS NULL OR recorded_to>:at)
            ORDER BY id LIMIT 5000
            """
        ),
        {"tenant": tenant_id, "at": decision_time},
    ).mappings().all()
    normalized_nodes = []
    for raw in nodes:
        row = dict(raw)
        row["attributes"] = _object(row.pop("attributes_json"))
        row["provenance"] = _object(row.pop("provenance_json"))
        normalized_nodes.append(row)
    normalized_edges = []
    for raw in edges:
        row = dict(raw)
        properties = _object(row.pop("properties_json"))
        row["properties"] = properties
        row.update(properties)
        row["provenance"] = _object(row.pop("provenance_json"))
        normalized_edges.append(row)
    return dict(target), normalized_nodes, normalized_edges


def _magnitude(signal: dict[str, Any]) -> tuple[float, float] | None:
    magnitude = _object(signal.get("magnitude_json"))
    measurement = _object(signal.get("measurement_json"))
    low = magnitude.get("low_pct", magnitude.get("low"))
    high = magnitude.get("high_pct", magnitude.get("high"))
    if low is not None and high is not None:
        try:
            return float(low), float(high)
        except (TypeError, ValueError):
            return None
    unit = str(measurement.get("unit") or measurement.get("uom") or "").lower()
    if unit in {"%", "pct", "percent", "percentage_point"}:
        try:
            value = float(magnitude["value"])
            return value, value
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _load_signals(db, *, tenant_id: str, decision_time: datetime):
    rows = db.execute(
        text(
            """
            SELECT id,subject_node_id,signal_type,direction,magnitude_json,
                   measurement_json,effective_from,effective_to,published_at,
                   available_at,source_system,source_record_id,source_policy_json,
                   provenance_json,confidence,status,simulation_only,
                   comparison_scope_json,expires_at
            FROM supply_signal_observation
            WHERE tenant_id=:tenant AND available_at<=:at
            ORDER BY available_at,id LIMIT 5000
            """
        ),
        {"tenant": tenant_id, "at": decision_time},
    ).mappings().all()
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        reason = None
        if row["expires_at"] is not None and _utc(row["expires_at"]) <= decision_time:
            reason = "stale"
        elif str(row["status"]) not in {"observed", "estimated", "simulated"}:
            reason = "status_not_eligible"
        elif (
            row["effective_from"] is not None
            and _utc(row["effective_from"]) > decision_time
        ) or (
            row["effective_to"] is not None
            and _utc(row["effective_to"]) <= decision_time
        ):
            reason = "outside_effective_period"
        bounds = _magnitude(row)
        source_policy = _object(row["source_policy_json"])
        provenance_chain = _list(row["provenance_json"])
        comparison_scope = _object(row["comparison_scope_json"])
        if reason is None and (not source_policy or not provenance_chain):
            reason = "source_governance_or_provenance_missing"
        if reason is None and str(
            comparison_scope.get("comparability_status") or ""
        ) in {"incomparable", "contested"}:
            reason = "comparison_scope_not_comparable"
        if reason is None and bounds is None:
            reason = "magnitude_not_comparable"
        normalized = {
            "id": str(row["id"]),
            "tenant_id": tenant_id,
            "subject_node_id": str(row["subject_node_id"]),
            "signal_type": str(row["signal_type"]),
            "direction": str(row["direction"]),
            "magnitude": _object(row["magnitude_json"]),
            "measurement": _object(row["measurement_json"]),
            "available_at": str(row["available_at"]),
            "expires_at": str(row["expires_at"]) if row["expires_at"] else None,
            "source_system": str(row["source_system"]),
            "source_record_id": str(row["source_record_id"]),
            "source_policy": source_policy,
            "provenance_chain": provenance_chain,
            "comparison_scope": comparison_scope,
            "confidence": float(row["confidence"]),
            "status": str(row["status"]),
            "simulation_only": bool(row["simulation_only"]),
        }
        if reason:
            excluded.append({
                "signal_id": normalized["id"],
                "reason": reason,
                "source_system": normalized["source_system"],
                "source_record_id": normalized["source_record_id"],
            })
        else:
            normalized["magnitude_low_pct"] = bounds[0]
            normalized["magnitude_high_pct"] = bounds[1]
            eligible.append(normalized)
    return eligible, excluded


def _supplier_observations(db, *, tenant_id: str, hypothesis_ids: list[str]):
    if not hypothesis_ids:
        return []
    rows = db.execute(
        text(
            """
            SELECT id,hypothesis_id,observation_type,supplier_ref,source_message_id,
                   observation_json,provenance_json,observed_at,recorded_by,recorded_at
            FROM supplier_hypothesis_observation
            WHERE tenant_id=:tenant
            ORDER BY observed_at,id
            """
        ),
        {"tenant": tenant_id},
    ).mappings().all()
    allowed = set(hypothesis_ids)
    return [
        {
            **dict(row),
            "observation_json": _object(row["observation_json"]),
            "provenance_json": _object(row["provenance_json"]),
            "authority": "supplier_observation_only",
            "execution_allowed": False,
        }
        for row in rows
        if str(row["hypothesis_id"]) in allowed
    ]


def _exposure(
    db,
    *,
    tenant_id: str,
    target: dict[str, Any],
    known_inputs: dict[str, Any],
) -> dict[str, Any]:
    result = {
        field: {"status": "unavailable", "reason": "authoritative_input_unavailable"}
        for field in sorted(KNOWN_EXPOSURE_FIELDS)
    }
    normalized_known: dict[str, Any] = {}
    for field, raw in known_inputs.items():
        if field not in KNOWN_EXPOSURE_FIELDS or not isinstance(raw, dict):
            continue
        if raw.get("value") is None or not raw.get("provenance"):
            result[field] = {
                "status": "unavailable",
                "reason": "value_and_provenance_required",
            }
            continue
        normalized_known[field] = dict(raw)
        result[field] = {
            **dict(raw),
            "status": "provided",
            "authority": "explicit_known_input",
        }
    tables = set(inspect(db.get_bind()).get_table_names())
    attributes = _object(target.get("attributes_json"))
    variant_id = str(
        attributes.get("variant_id")
        or (target.get("logical_key") if target.get("node_type") == "variant" else "")
        or ""
    )
    if (
        "inventory_projection_balance" in tables
        and variant_id
        and "current_atp" not in normalized_known
    ):
        rows = db.execute(
            text(
                """
                SELECT source,uom,quantity,status,projection_run_id
                FROM inventory_projection_balance
                WHERE tenant_id=:tenant AND variant_id=:variant
                  AND custody='available'
                """
            ),
            {"tenant": tenant_id, "variant": variant_id},
        ).fetchall()
        usable = [row for row in rows if str(row[3]) == "available"]
        sources = {str(row[0]) for row in usable}
        uoms = {str(row[1]) for row in usable}
        if usable and len(sources) > 1:
            result["current_atp"] = {
                "status": "contested",
                "reason": "multiple_inventory_projection_sources",
                "sources": sorted(sources),
            }
        elif usable and len(uoms) == 1:
            result["current_atp"] = {
                "status": "partially_available",
                "value": sum(float(row[2]) for row in usable),
                "uom": next(iter(uoms)),
                "basis": "projected_available_inventory_not_committed_atp",
                "source": next(iter(sources)),
                "projection_run_ids": sorted({str(row[4]) for row in usable}),
                "authority": "rebuildable_inventory_projection",
            }
        elif usable:
            result["current_atp"] = {
                "status": "incomparable",
                "reason": "multiple_uoms_require_effective_conversion",
                "uoms": sorted(uoms),
            }
        elif rows:
            result["current_atp"] = {
                "status": "quarantined",
                "reason": "inventory_projection_not_execution_eligible",
            }
    return {"fields": result, "known_inputs": normalized_known}


def create_grounded_hypothesis(
    db,
    *,
    tenant_id: str,
    target_node_id: str,
    decision_time: str,
    created_by: str,
    case_id: str | None = None,
    known_exposure: dict[str, Any] | None = None,
    supersedes_hypothesis_id: str | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    target_id = str(target_node_id or "").strip()
    actor = str(created_by or "").strip()
    at = _utc(decision_time)
    if not tenant or not target_id or not actor:
        raise ValueError("supply_hypothesis_scope_required")
    target, nodes, edges = _load_graph(
        db, tenant_id=tenant, target_node_id=target_id, decision_time=at
    )
    if target is None:
        raise ValueError("supply_target_not_in_tenant_graph")
    eligible_signals, excluded_signals = _load_signals(
        db, tenant_id=tenant, decision_time=at
    )
    predecessor_ids: list[str] = []
    if supersedes_hypothesis_id:
        predecessor = db.execute(
            text(
                """
                SELECT id,supersedes_hypothesis_id
                FROM causal_impact_hypothesis
                WHERE tenant_id=:tenant AND id=:id
                """
            ),
            {"tenant": tenant, "id": supersedes_hypothesis_id},
        ).mappings().first()
        if not predecessor:
            raise ValueError("supply_hypothesis_not_in_tenant")
        current = predecessor
        while current:
            predecessor_ids.append(str(current["id"]))
            parent = current["supersedes_hypothesis_id"]
            current = (
                db.execute(
                    text(
                        """
                        SELECT id,supersedes_hypothesis_id
                        FROM causal_impact_hypothesis
                        WHERE tenant_id=:tenant AND id=:id
                        """
                    ),
                    {"tenant": tenant, "id": parent},
                ).mappings().first()
                if parent else None
            )
    replies = _supplier_observations(
        db, tenant_id=tenant, hypothesis_ids=predecessor_ids
    )
    exposure = _exposure(
        db,
        tenant_id=tenant,
        target=target,
        known_inputs=known_exposure or {},
    )
    bundle = {
        "schema_version": 1,
        "tenant_id": tenant,
        "target_node_id": target_id,
        "decision_time": at.isoformat(),
        "nodes": nodes,
        "edges": edges,
        "eligible_signals": eligible_signals,
        "excluded_signals": excluded_signals,
        "supplier_observations": replies,
        "exposure": exposure,
        "source_status": {
            "eligible_signal_count": len(eligible_signals),
            "excluded_signal_count": len(excluded_signals),
            "graph_node_count": len(nodes),
            "graph_edge_count": len(edges),
        },
    }
    bundle_json = _json(bundle)
    bundle_hash = hashlib.sha256(bundle_json.encode()).hexdigest()
    bundle_id = hashlib.sha256(f"{tenant}|bundle|{bundle_hash}".encode()).hexdigest()
    if eligible_signals:
        hypothesis = build_grounded_impact_hypothesis(
            tenant_id=tenant,
            target_node_id=target_id,
            nodes=nodes,
            edges=edges,
            signals=eligible_signals,
            decision_time=at.isoformat(),
        )
    else:
        hypothesis = {
            "tenant_id": tenant,
            "target_node_id": target_id,
            "decision_time": at.isoformat(),
            "status": "no_verified_exposure",
            "reason": "no_current_comparable_evidence",
            "dependency_paths": [],
            "impact": None,
            "authority": "advisory_only",
            "execution_allowed": False,
        }
    reply_counts = {
        kind: sum(1 for row in replies if row["observation_type"] == kind)
        for kind in sorted(SUPPLIER_OBSERVATION_TYPES)
    }
    if hypothesis["status"] == "supported_hypothesis":
        if reply_counts["contradiction"]:
            hypothesis["status"] = "contested_hypothesis"
            hypothesis["causal_language"] = "contested_by_supplier_observation"
        elif reply_counts["confirmation"]:
            hypothesis["causal_language"] = "consistent_with_supplier_observation"
        if reply_counts["narrowing"]:
            hypothesis["scope_status"] = (
                "supplier_observation_narrows_scope_without_quantitative_authority"
            )
    hypothesis["supplier_observation_summary"] = reply_counts
    hypothesis["evidence_bundle_id"] = bundle_id
    hypothesis["supersedes_hypothesis_id"] = supersedes_hypothesis_id
    hypothesis["exposure"] = exposure["fields"]
    hypothesis["execution_allowed"] = False
    hypothesis["authority"] = "advisory_only"
    hypothesis_json = _json(hypothesis)
    hypothesis_id = hashlib.sha256(
        (
            f"{tenant}|hypothesis|{target_id}|{at.isoformat()}|{bundle_hash}|"
            f"{supersedes_hypothesis_id or ''}"
        ).encode()
    ).hexdigest()
    options = propose_procurement_options(hypothesis)
    option_id = hashlib.sha256(f"{hypothesis_id}|options|1".encode()).hexdigest()
    exists = db.execute(
        text(
            "SELECT 1 FROM causal_impact_hypothesis "
            "WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": tenant, "id": hypothesis_id},
    ).first()
    if not exists:
        bundle_exists = db.execute(
            text(
                "SELECT 1 FROM supply_evidence_bundle "
                "WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": tenant, "id": bundle_id},
        ).first()
        if not bundle_exists:
            db.execute(
                text(
                    """
                    INSERT INTO supply_evidence_bundle
                    (id,tenant_id,target_node_id,decision_time,bundle_hash,
                     bundle_json,created_by)
                    VALUES (:id,:tenant,:target,:at,:hash,:bundle,:actor)
                    """
                ),
                {
                    "id": bundle_id, "tenant": tenant, "target": target_id,
                    "at": at, "hash": bundle_hash, "bundle": bundle_json,
                    "actor": actor,
                },
            )
        db.execute(
            text(
                """
                INSERT INTO causal_impact_hypothesis
                (id,tenant_id,target_node_id,decision_time,hypothesis_json,status,
                 authority,evidence_bundle_id,supersedes_hypothesis_id,case_id,created_by)
                VALUES
                (:id,:tenant,:target,:at,:hypothesis,:status,'advisory_only',
                 :bundle,:supersedes,:case_id,:actor)
                """
            ),
            {
                "id": hypothesis_id, "tenant": tenant, "target": target_id,
                "at": at, "hypothesis": hypothesis_json,
                "status": hypothesis["status"], "bundle": bundle_id,
                "supersedes": supersedes_hypothesis_id,
                "case_id": str(case_id) if case_id else None, "actor": actor,
            },
        )
        db.execute(
            text(
                """
                INSERT INTO procurement_option_proposal
                (id,tenant_id,hypothesis_id,case_id,options_json,status,
                 authority,created_by)
                VALUES
                (:id,:tenant,:hypothesis,:case_id,:options,:status,
                 'proposal_only',:actor)
                """
            ),
            {
                "id": option_id, "tenant": tenant, "hypothesis": hypothesis_id,
                "case_id": str(case_id) if case_id else None,
                "options": _json(options), "status": options["status"], "actor": actor,
            },
        )
        db.commit()
    return {
        "hypothesis_id": hypothesis_id,
        "evidence_bundle_id": bundle_id,
        "hypothesis": hypothesis,
        "procurement_options": options,
        "idempotent_replay": bool(exists),
        "execution_allowed": False,
    }


def record_supplier_hypothesis_observation(
    db,
    *,
    tenant_id: str,
    hypothesis_id: str,
    observation_type: str,
    supplier_ref: str,
    source_message_id: str,
    observation: dict[str, Any],
    provenance: dict[str, Any],
    observed_at: str,
    recorded_by: str,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    hypothesis = str(hypothesis_id or "").strip()
    kind = str(observation_type or "").strip().lower()
    if kind not in SUPPLIER_OBSERVATION_TYPES:
        raise ValueError("supplier_hypothesis_observation_type_invalid")
    if not all((
        tenant, hypothesis, supplier_ref, source_message_id,
        observation, provenance, recorded_by,
    )):
        raise ValueError("supplier_hypothesis_observation_scope_required")
    owner = db.execute(
        text(
            "SELECT 1 FROM causal_impact_hypothesis "
            "WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": tenant, "id": hypothesis},
    ).first()
    if not owner:
        raise ValueError("supply_hypothesis_not_in_tenant")
    observed = _utc(observed_at)
    record_id = hashlib.sha256(
        f"{tenant}|{hypothesis}|{source_message_id}".encode()
    ).hexdigest()
    exists = db.execute(
        text(
            "SELECT 1 FROM supplier_hypothesis_observation "
            "WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": tenant, "id": record_id},
    ).first()
    if not exists:
        db.execute(
            text(
                """
                INSERT INTO supplier_hypothesis_observation
                (id,tenant_id,hypothesis_id,observation_type,supplier_ref,
                 source_message_id,observation_json,provenance_json,observed_at,
                 recorded_by)
                VALUES
                (:id,:tenant,:hypothesis,:kind,:supplier,:message,:observation,
                 :provenance,:observed,:actor)
                """
            ),
            {
                "id": record_id, "tenant": tenant, "hypothesis": hypothesis,
                "kind": kind, "supplier": str(supplier_ref),
                "message": str(source_message_id),
                "observation": _json(observation), "provenance": _json(provenance),
                "observed": observed, "actor": str(recorded_by),
            },
        )
        db.commit()
    return {
        "id": record_id,
        "hypothesis_id": hypothesis,
        "observation_type": kind,
        "authority": "supplier_observation_only",
        "can_authorize_execution": False,
        "requires_superseding_hypothesis": True,
        "idempotent_replay": bool(exists),
    }


def get_grounded_hypothesis(
    db, *, tenant_id: str, hypothesis_id: str
) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            SELECT h.id,h.target_node_id,h.decision_time,h.hypothesis_json,h.status,
                   h.authority,h.evidence_bundle_id,h.supersedes_hypothesis_id,
                   h.case_id,b.bundle_hash,b.bundle_json,p.options_json
            FROM causal_impact_hypothesis h
            LEFT JOIN supply_evidence_bundle b
              ON b.tenant_id=h.tenant_id AND b.id=h.evidence_bundle_id
            LEFT JOIN procurement_option_proposal p
              ON p.tenant_id=h.tenant_id AND p.hypothesis_id=h.id
            WHERE h.tenant_id=:tenant AND h.id=:id
            """
        ),
        {
            "tenant": str(tenant_id or "").strip(),
            "id": str(hypothesis_id or "").strip(),
        },
    ).mappings().first()
    if not row:
        raise ValueError("supply_hypothesis_not_in_tenant")
    return {
        "hypothesis_id": str(row["id"]),
        "target_node_id": str(row["target_node_id"]),
        "decision_time": str(row["decision_time"]),
        "hypothesis": _object(row["hypothesis_json"]),
        "status": str(row["status"]),
        "authority": str(row["authority"]),
        "evidence_bundle_id": row["evidence_bundle_id"],
        "evidence_bundle_hash": row["bundle_hash"],
        "evidence_bundle": _object(row["bundle_json"]),
        "supersedes_hypothesis_id": row["supersedes_hypothesis_id"],
        "case_id": row["case_id"],
        "procurement_options": _object(row["options_json"]),
        "execution_allowed": False,
    }


def reevaluate_grounded_hypothesis(
    db,
    *,
    tenant_id: str,
    hypothesis_id: str,
    decision_time: str,
    created_by: str,
) -> dict[str, Any]:
    existing = get_grounded_hypothesis(
        db, tenant_id=tenant_id, hypothesis_id=hypothesis_id
    )
    known = (
        existing["evidence_bundle"].get("exposure", {}).get("known_inputs", {})
    )
    return create_grounded_hypothesis(
        db,
        tenant_id=tenant_id,
        target_node_id=existing["target_node_id"],
        decision_time=decision_time,
        created_by=created_by,
        case_id=existing.get("case_id"),
        known_exposure=known,
        supersedes_hypothesis_id=hypothesis_id,
    )
