"""Governed import contract for real supplier/component/location exposure.

The manifest binds tenant-owned operational identities to the supply graph.
Public market observations can only affect a target after an approved subject
mapping and a time-valid dependency path exist. Imports are versioned,
idempotent and advisory-only; they never grant procurement authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from src.app.services.supply_graph_repository import (
    NODE_TYPES,
    RELATIONSHIP_TYPES,
    put_edge_revision,
    put_node_revision,
)


SCHEMA_VERSION = "supply_exposure.v1"
MAX_NODES = 500
MAX_EDGES = 2_000


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required(value: Any, error: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error)
    return normalized


def _manifest_hash(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def import_supply_exposure_manifest(
    db,
    *,
    tenant_id: str,
    manifest: dict[str, Any],
    approved_by: str,
    imported_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Validate and atomically project one authoritative exposure snapshot."""
    if str(manifest.get("schema_version") or "") != SCHEMA_VERSION:
        raise ValueError("supply_exposure_schema_version_unsupported")
    tenant = _required(tenant_id, "supply_graph_tenant_required")
    actor = _required(approved_by, "supply_exposure_approver_required")
    source = _required(manifest.get("source_system"), "supply_exposure_source_required")
    snapshot = _required(manifest.get("snapshot_id"), "supply_exposure_snapshot_required")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict) or not provenance:
        raise ValueError("supply_exposure_provenance_required")
    try:
        revision = int(manifest.get("revision"))
    except (TypeError, ValueError) as exc:
        raise ValueError("supply_exposure_revision_invalid") from exc
    if revision < 1:
        raise ValueError("supply_exposure_revision_invalid")

    decision_time = _utc(imported_at or datetime.now(timezone.utc))
    observed_at = _utc(manifest.get("observed_at"))
    valid_from = _utc(manifest.get("valid_from") or observed_at)
    fresh_until = _utc(manifest.get("fresh_until"))
    if observed_at > decision_time:
        raise ValueError("supply_exposure_future_observation")
    if fresh_until <= decision_time or fresh_until <= observed_at:
        raise ValueError("supply_exposure_manifest_stale")

    nodes = manifest.get("nodes")
    edges = manifest.get("edges")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES:
        raise ValueError("supply_exposure_node_count_invalid")
    if not isinstance(edges, list) or len(edges) > MAX_EDGES:
        raise ValueError("supply_exposure_edge_count_invalid")

    node_specs: dict[str, dict[str, Any]] = {}
    for raw in nodes:
        if not isinstance(raw, dict):
            raise ValueError("supply_exposure_node_invalid")
        key = _required(raw.get("logical_key"), "supply_exposure_node_identity_required")
        kind = _required(raw.get("node_type"), "supply_exposure_node_identity_required")
        if key in node_specs:
            raise ValueError("supply_exposure_node_duplicate")
        if kind not in NODE_TYPES:
            raise ValueError("supply_node_type_invalid")
        _required(raw.get("label"), "supply_exposure_node_identity_required")
        node_specs[key] = raw

    edge_specs: list[dict[str, Any]] = []
    edge_keys: set[str] = set()
    for raw in edges:
        if not isinstance(raw, dict):
            raise ValueError("supply_exposure_edge_invalid")
        key = _required(raw.get("logical_key"), "supply_exposure_edge_identity_required")
        relationship = _required(
            raw.get("relationship_type"),
            "supply_exposure_edge_identity_required",
        )
        if key in edge_keys:
            raise ValueError("supply_exposure_edge_duplicate")
        if relationship not in RELATIONSHIP_TYPES:
            raise ValueError("supply_relationship_type_invalid")
        left = _required(raw.get("from_logical_key"), "supply_exposure_edge_endpoint_invalid")
        right = _required(raw.get("to_logical_key"), "supply_exposure_edge_endpoint_invalid")
        if left not in node_specs or right not in node_specs:
            raise ValueError("supply_exposure_edge_endpoint_invalid")
        try:
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise ValueError("supply_relationship_confidence_invalid") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("supply_relationship_confidence_invalid")
        edge_keys.add(key)
        edge_specs.append(raw)

    digest = _manifest_hash(manifest)
    common = {
        "snapshot_id": snapshot,
        "snapshot_revision": revision,
        "manifest_hash": digest,
        "observed_at": observed_at.isoformat(),
        "fresh_until": fresh_until.isoformat(),
        "approved_by": actor,
    }
    node_ids: dict[str, str] = {}
    try:
        for key, raw in node_specs.items():
            record = _required(
                raw.get("source_record_id") or key,
                "supply_exposure_node_identity_required",
            )
            result = put_node_revision(
                db,
                tenant_id=tenant,
                logical_key=key,
                node_type=str(raw["node_type"]),
                label=str(raw["label"]),
                source_system=source,
                source_record_id=f"{snapshot}:r{revision}:node:{record}",
                provenance={**provenance, **common, "record_id": record},
                valid_from=valid_from,
                attributes={**dict(raw.get("attributes") or {}), **common},
                identity_status=str(raw.get("identity_status") or "resolved"),
                evidence_status="approved_observation",
                revision_reason=str(raw.get("revision_reason") or "exposure_snapshot"),
                simulation_only=False,
                recorded_at=decision_time,
                commit=False,
            )
            node_ids[key] = str(result["id"])

        for raw in edge_specs:
            record = _required(
                raw.get("source_record_id") or raw["logical_key"],
                "supply_exposure_edge_identity_required",
            )
            put_edge_revision(
                db,
                tenant_id=tenant,
                logical_key=str(raw["logical_key"]),
                from_node_id=node_ids[str(raw["from_logical_key"])],
                to_node_id=node_ids[str(raw["to_logical_key"])],
                relationship_type=str(raw["relationship_type"]),
                source_system=source,
                source_record_id=f"{snapshot}:r{revision}:edge:{record}",
                provenance={**provenance, **common, "record_id": record},
                valid_from=valid_from,
                confidence=float(raw["confidence"]),
                properties={**dict(raw.get("properties") or {}), **common},
                evidence_status="approved_observation",
                revision_reason=str(raw.get("revision_reason") or "exposure_snapshot"),
                simulation_only=False,
                recorded_at=decision_time,
                commit=False,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "tenant_id": tenant,
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot,
        "revision": revision,
        "manifest_hash": digest,
        "node_count": len(node_specs),
        "edge_count": len(edge_specs),
        "fresh_until": fresh_until.isoformat(),
        "authority": "advisory_only",
        "execution_allowed": False,
    }
