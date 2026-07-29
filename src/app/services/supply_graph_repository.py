"""Tenant-scoped operational repository for governed supply dependencies.

The repository stores append-only bitemporal revisions. It deliberately does
not infer identities or public-source exposure: callers must approve exact
subject mappings before observations can become advisory supply signals.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.app.services.market_source_registry import load_market_source_registry


NODE_TYPES = frozenset({
    "product",
    "variant",
    "component",
    "material",
    "supplier",
    "facility",
    "location",
    "logistics_lane",
    "commodity_index",
    "price_index",
})
RELATIONSHIP_TYPES = frozenset({
    "composed_of",
    "qualified_substitute_for",
    "compatible_with",
    "supplied_by",
    "manufactured_at",
    "transported_via",
    "indexed_to",
    "certified_for",
})
IDENTITY_STATUSES = frozenset({"resolved", "unresolved", "contested"})
MAPPING_STATUSES = frozenset({"approved", "quarantined", "rejected"})


def _tenant(value: str) -> str:
    tenant = str(value or "").strip()
    if not tenant:
        raise ValueError("supply_graph_tenant_required")
    return tenant


def _utc(value: datetime | str | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def put_node_revision(
    db,
    *,
    tenant_id: str,
    logical_key: str,
    node_type: str,
    label: str,
    source_system: str,
    source_record_id: str,
    provenance: dict[str, Any],
    valid_from: datetime | str,
    attributes: dict[str, Any] | None = None,
    identity_status: str = "resolved",
    evidence_status: str = "observed",
    revision_reason: str = "initial_observation",
    simulation_only: bool = False,
    recorded_at: datetime | str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    key = str(logical_key or "").strip()
    kind = str(node_type or "").strip()
    status = str(identity_status or "").strip()
    if not key or not str(label or "").strip():
        raise ValueError("supply_node_identity_required")
    if kind not in NODE_TYPES:
        raise ValueError("supply_node_type_invalid")
    if status not in IDENTITY_STATUSES:
        raise ValueError("supply_node_identity_status_invalid")
    if not source_system or not source_record_id or not provenance:
        raise ValueError("supply_node_provenance_required")
    duplicate = db.execute(text(
        "SELECT id,logical_key,node_type,supersedes_id,identity_status,recorded_from "
        "FROM supply_node WHERE tenant_id=:tenant AND source_system=:source "
        "AND source_record_id=:record LIMIT 1"
    ), {
        "tenant": tenant, "source": str(source_system),
        "record": str(source_record_id),
    }).mappings().first()
    if duplicate:
        return {
            **dict(duplicate), "tenant_id": tenant,
            "recorded_from": _utc(duplicate["recorded_from"]).isoformat(),
            "idempotent_replay": True,
        }
    recorded = _utc(recorded_at)
    effective = _utc(valid_from)
    current = db.execute(text(
        "SELECT id FROM supply_node WHERE tenant_id=:tenant AND logical_key=:key "
        "AND recorded_to IS NULL ORDER BY recorded_from DESC LIMIT 1"
    ), {"tenant": tenant, "key": key}).mappings().first()
    supersedes = str(current["id"]) if current else None
    if supersedes:
        db.execute(text(
            "UPDATE supply_node SET recorded_to=:recorded, valid_to=COALESCE(valid_to,:effective) "
            "WHERE id=:id AND tenant_id=:tenant AND recorded_to IS NULL"
        ), {
            "recorded": recorded, "effective": effective,
            "id": supersedes, "tenant": tenant,
        })
    row_id = uuid.uuid4().hex
    db.execute(text(
        "INSERT INTO supply_node "
        "(id,tenant_id,node_type,label,attributes_json,valid_from,valid_to,"
        "source_system,source_record_id,provenance_json,evidence_status,"
        "simulation_only,logical_key,recorded_from,recorded_to,supersedes_id,"
        "revision_reason,identity_status) VALUES "
        "(:id,:tenant,:kind,:label,:attributes,:valid_from,NULL,:source_system,"
        ":source_record_id,:provenance,:evidence_status,:simulation_only,:logical_key,"
        ":recorded_from,NULL,:supersedes,:reason,:identity_status)"
    ), {
        "id": row_id, "tenant": tenant, "kind": kind, "label": str(label).strip(),
        "attributes": _json(attributes or {}), "valid_from": effective,
        "source_system": str(source_system),
        "source_record_id": str(source_record_id),
        "provenance": _json(provenance), "evidence_status": evidence_status,
        "simulation_only": bool(simulation_only), "logical_key": key,
        "recorded_from": recorded, "supersedes": supersedes,
        "reason": str(revision_reason), "identity_status": status,
    })
    if commit:
        db.commit()
    return {
        "id": row_id, "tenant_id": tenant, "logical_key": key,
        "node_type": kind, "supersedes_id": supersedes,
        "identity_status": status, "recorded_from": recorded.isoformat(),
    }


def put_edge_revision(
    db,
    *,
    tenant_id: str,
    logical_key: str,
    from_node_id: str,
    to_node_id: str,
    relationship_type: str,
    source_system: str,
    source_record_id: str,
    provenance: dict[str, Any],
    valid_from: datetime | str,
    confidence: float,
    properties: dict[str, Any] | None = None,
    evidence_status: str = "observed",
    revision_reason: str = "initial_observation",
    simulation_only: bool = False,
    recorded_at: datetime | str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    key = str(logical_key or "").strip()
    relationship = str(relationship_type or "").strip()
    if not key or relationship not in RELATIONSHIP_TYPES:
        raise ValueError("supply_relationship_type_invalid")
    confidence_value = float(confidence)
    if not 0.0 <= confidence_value <= 1.0:
        raise ValueError("supply_relationship_confidence_invalid")
    duplicate = db.execute(text(
        "SELECT id,logical_key,relationship_type,supersedes_id "
        "FROM supply_dependency_edge WHERE tenant_id=:tenant "
        "AND source_system=:source AND source_record_id=:record LIMIT 1"
    ), {
        "tenant": tenant, "source": str(source_system),
        "record": str(source_record_id),
    }).mappings().first()
    if duplicate:
        return {
            **dict(duplicate), "tenant_id": tenant, "idempotent_replay": True,
        }
    node_ids = {str(from_node_id), str(to_node_id)}
    rows = db.execute(text(
        "SELECT id FROM supply_node WHERE tenant_id=:tenant AND id IN (:left,:right) "
        "AND recorded_to IS NULL AND valid_to IS NULL"
    ), {
        "tenant": tenant, "left": str(from_node_id), "right": str(to_node_id),
    }).mappings().all()
    if {str(row["id"]) for row in rows} != node_ids:
        raise ValueError("supply_relationship_endpoint_invalid")
    recorded = _utc(recorded_at)
    effective = _utc(valid_from)
    current = db.execute(text(
        "SELECT id FROM supply_dependency_edge WHERE tenant_id=:tenant "
        "AND logical_key=:key AND recorded_to IS NULL "
        "ORDER BY recorded_from DESC LIMIT 1"
    ), {"tenant": tenant, "key": key}).mappings().first()
    supersedes = str(current["id"]) if current else None
    if supersedes:
        db.execute(text(
            "UPDATE supply_dependency_edge SET recorded_to=:recorded,"
            "valid_to=COALESCE(valid_to,:effective) WHERE id=:id "
            "AND tenant_id=:tenant AND recorded_to IS NULL"
        ), {
            "recorded": recorded, "effective": effective,
            "id": supersedes, "tenant": tenant,
        })
    row_id = uuid.uuid4().hex
    db.execute(text(
        "INSERT INTO supply_dependency_edge "
        "(id,tenant_id,from_node_id,to_node_id,relationship_type,properties_json,"
        "confidence,valid_from,valid_to,source_system,source_record_id,provenance_json,"
        "evidence_status,simulation_only,logical_key,recorded_from,recorded_to,"
        "supersedes_id,revision_reason) VALUES "
        "(:id,:tenant,:from_id,:to_id,:relationship,:properties,:confidence,"
        ":valid_from,NULL,:source_system,:source_record_id,:provenance,"
        ":evidence_status,:simulation_only,:logical_key,:recorded_from,NULL,"
        ":supersedes,:reason)"
    ), {
        "id": row_id, "tenant": tenant, "from_id": str(from_node_id),
        "to_id": str(to_node_id), "relationship": relationship,
        "properties": _json(properties or {}), "confidence": confidence_value,
        "valid_from": effective, "source_system": str(source_system),
        "source_record_id": str(source_record_id),
        "provenance": _json(provenance), "evidence_status": evidence_status,
        "simulation_only": bool(simulation_only), "logical_key": key,
        "recorded_from": recorded, "supersedes": supersedes,
        "reason": str(revision_reason),
    })
    if commit:
        db.commit()
    return {
        "id": row_id, "tenant_id": tenant, "logical_key": key,
        "relationship_type": relationship, "supersedes_id": supersedes,
    }


def bounded_dependency_paths(
    db,
    *,
    tenant_id: str,
    source_node_id: str,
    target_node_id: str,
    at: datetime | str | None = None,
    max_depth: int = 6,
    max_paths: int = 50,
    max_edges: int = 2_000,
) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    depth = max(1, min(int(max_depth), 8))
    path_limit = max(1, min(int(max_paths), 100))
    edge_limit = max(1, min(int(max_edges), 5_000))
    stamp = _utc(at)
    edges = db.execute(text(
        "SELECT id,from_node_id,to_node_id,relationship_type,confidence,properties_json "
        "FROM supply_dependency_edge WHERE tenant_id=:tenant AND recorded_to IS NULL "
        "AND valid_from<=:at AND (valid_to IS NULL OR valid_to>:at) "
        "ORDER BY id LIMIT :limit"
    ), {"tenant": tenant, "at": stamp, "limit": edge_limit + 1}).mappings().all()
    truncated = len(edges) > edge_limit
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stale_edge_count = 0
    for raw in edges[:edge_limit]:
        row = dict(raw)
        row["properties"] = json.loads(row.pop("properties_json") or "{}")
        fresh_until = row["properties"].get("fresh_until")
        if fresh_until:
            try:
                if _utc(fresh_until) <= stamp:
                    stale_edge_count += 1
                    continue
            except (TypeError, ValueError):
                stale_edge_count += 1
                continue
        adjacency[str(row["from_node_id"])].append(row)
    queue = deque([(str(source_node_id), [], {str(source_node_id)})])
    found: list[list[dict[str, Any]]] = []
    while queue and len(found) < path_limit:
        node, path, seen = queue.popleft()
        if len(path) >= depth:
            continue
        for edge in adjacency.get(node, []):
            nxt = str(edge["to_node_id"])
            if nxt in seen:
                continue
            candidate = [*path, edge]
            if nxt == str(target_node_id):
                found.append(candidate)
                if len(found) >= path_limit:
                    break
            else:
                queue.append((nxt, candidate, seen | {nxt}))
    return {
        "tenant_id": tenant,
        "source_node_id": str(source_node_id),
        "target_node_id": str(target_node_id),
        "paths": found,
        "max_depth": depth,
        "truncated": truncated or len(found) >= path_limit,
        "stale_edge_count": stale_edge_count,
        "freshness_status": (
            "degraded_stale_edges_excluded" if stale_edge_count else "current_or_undeclared"
        ),
        "authority": "advisory_only",
        "execution_allowed": False,
    }


def graph_quality(db, *, tenant_id: str) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    nodes = db.execute(text(
        "SELECT id,node_type,identity_status FROM supply_node WHERE tenant_id=:tenant "
        "AND recorded_to IS NULL AND valid_to IS NULL"
    ), {"tenant": tenant}).mappings().all()
    edges = db.execute(text(
        "SELECT from_node_id,to_node_id,relationship_type,properties_json "
        "FROM supply_dependency_edge WHERE tenant_id=:tenant AND recorded_to IS NULL "
        "AND valid_to IS NULL"
    ), {"tenant": tenant}).mappings().all()
    incident = {
        str(value)
        for row in edges
        for value in (row["from_node_id"], row["to_node_id"])
    }
    actionable = [
        row for row in nodes
        if row["node_type"] in {"product", "variant"}
        and row["identity_status"] == "resolved"
    ]
    connected = sum(1 for row in actionable if str(row["id"]) in incident)
    supplier_counts: dict[str, int] = defaultdict(int)
    supplier_spend: dict[str, float] = defaultdict(float)
    for row in edges:
        if row["relationship_type"] == "supplied_by":
            supplier_id = str(row["to_node_id"])
            supplier_counts[supplier_id] += 1
            try:
                properties = json.loads(row["properties_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                properties = {}
            try:
                spend = float(properties.get("attributable_spend_minor") or 0)
            except (TypeError, ValueError):
                spend = 0.0
            supplier_spend[supplier_id] += max(0.0, spend)
    total_supplier_links = sum(supplier_counts.values())
    concentration = (
        sum((count / total_supplier_links) ** 2 for count in supplier_counts.values())
        if total_supplier_links else None
    )
    total_supplier_spend = sum(supplier_spend.values())
    spend_concentration = (
        sum(
            (spend / total_supplier_spend) ** 2
            for spend in supplier_spend.values()
            if spend > 0
        )
        if total_supplier_spend else None
    )
    unresolved = sum(1 for row in nodes if row["identity_status"] != "resolved")
    return {
        "tenant_id": tenant,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "unresolved_identity_count": unresolved,
        "dependency_completeness": (
            round(connected / len(actionable), 4) if actionable else None
        ),
        "supplier_concentration_hhi": (
            round(concentration, 4) if concentration is not None else None
        ),
        "supplier_spend_concentration_hhi": (
            round(spend_concentration, 4)
            if spend_concentration is not None else None
        ),
        "attributable_supplier_spend_minor": round(total_supplier_spend),
        "supplier_spend_concentration_status": (
            "observed" if spend_concentration is not None
            else "undefined_no_attributable_spend"
        ),
        "status": (
            "incomplete" if unresolved or connected < len(actionable) else "complete"
        ),
        "authority": "advisory_only",
    }


def approve_subject_mapping(
    db,
    *,
    tenant_id: str,
    source_id: str,
    external_subject_id: str,
    subject_node_id: str,
    mapping_basis: str,
    provenance: dict[str, Any],
    approved_by: str,
    valid_from: datetime | str | None = None,
) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    if not all((
        source_id, external_subject_id, subject_node_id, mapping_basis,
        provenance, approved_by,
    )):
        raise ValueError("market_subject_mapping_authority_required")
    if str(source_id) not in load_market_source_registry():
        raise ValueError("external_market_source_not_registered")
    exists = db.execute(text(
        "SELECT id FROM supply_node WHERE tenant_id=:tenant AND id=:node "
        "AND recorded_to IS NULL AND valid_to IS NULL"
    ), {"tenant": tenant, "node": subject_node_id}).first()
    if not exists:
        raise ValueError("market_subject_mapping_node_invalid")
    stamp = _utc(valid_from)
    mapping_id = uuid.uuid4().hex
    db.execute(text(
        "INSERT INTO market_subject_mapping "
        "(id,tenant_id,source_id,external_subject_id,subject_node_id,status,"
        "mapping_basis,provenance_json,approved_by,valid_from,valid_to,recorded_at) "
        "VALUES (:id,:tenant,:source,:external,:node,'approved',:basis,:provenance,"
        ":approved_by,:valid_from,NULL,:recorded_at)"
    ), {
        "id": mapping_id, "tenant": tenant, "source": str(source_id),
        "external": str(external_subject_id), "node": str(subject_node_id),
        "basis": str(mapping_basis), "provenance": _json(provenance),
        "approved_by": str(approved_by), "valid_from": stamp, "recorded_at": stamp,
    })
    db.commit()
    return {
        "id": mapping_id, "tenant_id": tenant, "status": "approved",
        "external_subject_id": str(external_subject_id),
        "subject_node_id": str(subject_node_id),
    }


def project_public_observations(
    db,
    *,
    tenant_id: str,
    source_id: str,
    source_revision: int,
    observations: list[dict[str, Any]],
    fresh_until: datetime | str | None,
) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    projected = quarantined = existing = 0
    reasons: dict[str, int] = defaultdict(int)
    expiry = _utc(fresh_until) if fresh_until else None
    for observation in observations[:100]:
        external = str(observation.get("subject_id") or "").strip()
        record_id = str(observation.get("source_record_id") or "").strip()
        mappings = db.execute(text(
            "SELECT id,subject_node_id FROM market_subject_mapping "
            "WHERE tenant_id=:tenant AND source_id=:source AND external_subject_id=:external "
            "AND status='approved' AND valid_to IS NULL ORDER BY recorded_at DESC"
        ), {
            "tenant": tenant, "source": source_id, "external": external,
        }).mappings().all()
        reason = (
            "subject_mapping_missing" if not mappings
            else "subject_mapping_ambiguous" if len(mappings) > 1
            else None
        )
        if reason:
            already = db.execute(text(
                "SELECT id FROM supply_signal_quarantine WHERE tenant_id=:tenant "
                "AND source_id=:source AND source_record_id=:record "
                "AND source_revision=:revision"
            ), {
                "tenant": tenant, "source": source_id, "record": record_id,
                "revision": int(source_revision),
            }).first()
            if already:
                existing += 1
            else:
                db.execute(text(
                    "INSERT INTO supply_signal_quarantine "
                    "(id,tenant_id,source_id,source_record_id,source_revision,"
                    "external_subject_id,reason,observation_json,created_at) VALUES "
                    "(:id,:tenant,:source,:record,:revision,:external,:reason,:payload,:created)"
                ), {
                    "id": uuid.uuid4().hex, "tenant": tenant, "source": source_id,
                    "record": record_id, "revision": int(source_revision),
                    "external": external, "reason": reason,
                    "payload": _json(observation), "created": _utc(),
                })
                quarantined += 1
                reasons[reason] += 1
            continue
        mapping = mappings[0]
        measurement = observation.get("measurement") or {}
        comparison_scope = {
            "geography": observation.get("geography"),
            "effective_from": observation.get("effective_from"),
            "effective_to": observation.get("effective_to"),
            "publication": observation.get("published_at"),
            "revision": int(source_revision),
            "measurement_definition": observation.get("measurement_definition"),
            "currency": observation.get("currency"),
            "uom": observation.get("uom"),
            "supply_chain_stage": (
                measurement.get("supply_chain_stage") or "unspecified"
            ),
        }
        stored_record_id = f"{record_id}:revision:{int(source_revision)}"
        already = db.execute(text(
            "SELECT id FROM supply_signal_observation WHERE tenant_id=:tenant "
            "AND source_system=:source_system AND source_record_id=:record"
        ), {
            "tenant": tenant,
            "source_system": str(observation.get("source_system") or source_id),
            "record": stored_record_id,
        }).first()
        if already:
            existing += 1
        else:
            signal_id = uuid.uuid4().hex
            db.execute(text(
                "INSERT INTO supply_signal_observation "
                "(id,tenant_id,subject_node_id,signal_type,direction,magnitude_json,"
                "measurement_json,effective_from,effective_to,published_at,available_at,"
                "source_system,source_record_id,source_policy_json,provenance_json,"
                "confidence,status,simulation_only,mapping_id,comparison_scope_json,"
                "source_revision,expires_at) VALUES "
                "(:id,:tenant,:node,:signal,:direction,:magnitude,:measurement,"
                ":effective_from,:effective_to,:published_at,:available_at,:source_system,"
                ":source_record_id,:source_policy,:provenance,:confidence,'observed',"
                ":simulation_only,:mapping_id,:scope,:revision,:expires_at)"
            ), {
                "id": signal_id, "tenant": tenant,
                "node": str(mapping["subject_node_id"]),
                "signal": str(observation.get("signal_type") or "unknown"),
                "direction": str(observation.get("direction") or "unknown"),
                "magnitude": _json({
                    "value": measurement.get("value"),
                    "status": (
                        "observed_value" if measurement.get("value") is not None
                        else "undefined"
                    ),
                }),
                "measurement": _json(measurement),
                "effective_from": _utc(observation.get("effective_from")),
                "effective_to": (
                    _utc(observation["effective_to"])
                    if observation.get("effective_to") else None
                ),
                "published_at": _utc(observation.get("published_at")),
                "available_at": _utc(observation.get("available_at")),
                "source_system": str(observation.get("source_system") or source_id),
                "source_record_id": (
                    stored_record_id
                ),
                "source_policy": _json(observation.get("source_policy") or {}),
                "provenance": _json(observation.get("provenance_chain") or []),
                "confidence": float(observation.get("confidence") or 0.7),
                "simulation_only": bool(observation.get("simulation_only", False)),
                "mapping_id": str(mapping["id"]), "scope": _json(comparison_scope),
                "revision": int(source_revision), "expires_at": expiry,
            })
            projected += 1
    db.commit()
    return {
        "tenant_id": tenant, "source_id": source_id,
        "source_revision": int(source_revision), "projected": projected,
        "quarantined": quarantined, "existing": existing,
        "quarantine_reasons": dict(reasons),
        "authority": "advisory_only", "execution_allowed": False,
    }


def project_latest_public_fetch(
    db,
    *,
    tenant_id: str,
    source_id: str,
) -> dict[str, Any]:
    """Project the latest durable normalized fetch through approved mappings."""
    tenant = _tenant(tenant_id)
    row = db.execute(text(
        "SELECT revision_number,normalized_json,expires_at,outcome "
        "FROM market_source_fetch_revision WHERE tenant_id=:tenant AND source_id=:source "
        "ORDER BY revision_number DESC LIMIT 1"
    ), {"tenant": tenant, "source": source_id}).mappings().first()
    if not row:
        return {
            "tenant_id": tenant, "source_id": source_id,
            "outcome": "never_fetched", "projected": 0,
            "authority": "advisory_only", "execution_allowed": False,
        }
    if not row["normalized_json"] or row["outcome"] not in {"observed", "not_modified"}:
        return {
            "tenant_id": tenant, "source_id": source_id,
            "outcome": "source_not_projectable", "projected": 0,
            "source_outcome": row["outcome"], "authority": "advisory_only",
            "execution_allowed": False,
        }
    return {
        "outcome": "projected",
        **project_public_observations(
            db,
            tenant_id=tenant,
            source_id=source_id,
            source_revision=int(row["revision_number"]),
            observations=json.loads(row["normalized_json"]),
            fresh_until=row["expires_at"],
        ),
    }


def public_source_health(
    db,
    *,
    tenant_id: str,
    source_id: str,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    tenant = _tenant(tenant_id)
    stamp = _utc(now)
    row = db.execute(text(
        "SELECT outcome,retrieved_at,expires_at,error_code,revision_number "
        "FROM market_source_fetch_revision WHERE tenant_id=:tenant AND source_id=:source "
        "ORDER BY revision_number DESC LIMIT 1"
    ), {"tenant": tenant, "source": source_id}).mappings().first()
    if not row:
        status = "never_fetched"
        return {
            "tenant_id": tenant, "source_id": source_id, "status": status,
            "complete": False, "fresh": False, "authority": "advisory_only",
        }
    expiry = _utc(row["expires_at"])
    fresh = expiry > stamp and row["outcome"] in {"observed", "not_modified"}
    return {
        "tenant_id": tenant, "source_id": source_id,
        "status": "healthy" if fresh else (
            "stale" if row["outcome"] in {"observed", "not_modified"} else "unavailable"
        ),
        "outcome": row["outcome"], "revision_number": int(row["revision_number"]),
        "retrieved_at": _utc(row["retrieved_at"]).isoformat(),
        "fresh_until": expiry.isoformat(), "fresh": fresh,
        "complete": bool(row["outcome"] in {"observed", "not_modified"}),
        "error_code": row["error_code"], "authority": "advisory_only",
    }
