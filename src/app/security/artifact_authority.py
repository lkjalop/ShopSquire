"""Durable, fail-closed authority for untrusted artifacts.

Artifacts are observations, never instructions.  Consequential actions may bind to an
artifact only when the exact tenant, SHA-256 and verdict version are still current and
clean.  Verdict history is append-only so a late security result cannot rewrite the
evidence that an earlier decision used.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from sqlalchemy import text


class ArtifactState(str, Enum):
    RECEIVED = "received"
    ADMITTED = "admitted"
    PENDING = "pending"
    CLEAN = "clean"
    QUARANTINED = "quarantined"
    DEGRADED = "degraded"
    SUPERSEDED = "superseded"


_ALLOWED_TRANSITIONS = {
    ArtifactState.RECEIVED: {ArtifactState.ADMITTED, ArtifactState.QUARANTINED, ArtifactState.DEGRADED},
    ArtifactState.ADMITTED: {ArtifactState.PENDING, ArtifactState.QUARANTINED, ArtifactState.DEGRADED},
    ArtifactState.PENDING: {ArtifactState.CLEAN, ArtifactState.QUARANTINED, ArtifactState.DEGRADED},
    # A late verdict does not mutate the old row; it appends a new version.
    ArtifactState.CLEAN: {ArtifactState.QUARANTINED, ArtifactState.DEGRADED, ArtifactState.SUPERSEDED},
    ArtifactState.QUARANTINED: {ArtifactState.SUPERSEDED},
    ArtifactState.DEGRADED: {ArtifactState.PENDING, ArtifactState.CLEAN, ArtifactState.QUARANTINED, ArtifactState.SUPERSEDED},
    ArtifactState.SUPERSEDED: set(),
}


@dataclass(frozen=True)
class ArtifactAuthorityResult:
    allowed: bool
    reason: str
    artifact_ids: tuple[str, ...] = ()
    blocked_states: tuple[str, ...] = ()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state(value: str | ArtifactState) -> ArtifactState:
    return value if isinstance(value, ArtifactState) else ArtifactState(str(value or "").strip().lower())


def record_verdict(
    db,
    *,
    artifact_id: str,
    tenant_id: str,
    artifact_sha256: str,
    state: str | ArtifactState,
    reason: str,
    case_id: str | None = None,
    source_type: str = "upload",
    coverage: Mapping[str, Any] | None = None,
    expected_previous_version: int | None = None,
) -> dict[str, Any]:
    """Append one verdict version using optimistic version checking."""
    target = _state(state)
    current = db.execute(
        text(
            "SELECT id, verdict_version, state FROM artifact_security_verdicts "
            "WHERE tenant_id=:tenant AND artifact_id=:artifact "
            "ORDER BY verdict_version DESC LIMIT 1"
        ),
        {"tenant": tenant_id, "artifact": artifact_id},
    ).mappings().first()
    previous_version = int(current["verdict_version"]) if current else 0
    if expected_previous_version is not None and previous_version != int(expected_previous_version):
        raise ValueError("artifact_verdict_version_conflict")
    if current:
        previous_state = _state(current["state"])
        if target not in _ALLOWED_TRANSITIONS[previous_state]:
            raise ValueError(f"illegal_artifact_transition:{previous_state.value}->{target.value}")
    elif target != ArtifactState.RECEIVED:
        raise ValueError("first_artifact_state_must_be_received")

    row_id = uuid.uuid4().hex
    version = previous_version + 1
    db.execute(
        text(
            "INSERT INTO artifact_security_verdicts "
            "(id, artifact_id, tenant_id, case_id, artifact_sha256, source_type, "
            " verdict_version, state, reason, coverage_json, supersedes_verdict_id, created_at) "
            "VALUES (:id,:artifact,:tenant,:case_id,:sha,:source,:version,:state,:reason,:coverage,:supersedes,:created)"
        ),
        {
            "id": row_id,
            "artifact": artifact_id,
            "tenant": tenant_id,
            "case_id": case_id,
            "sha": str(artifact_sha256).lower(),
            "source": source_type,
            "version": version,
            "state": target.value,
            "reason": reason,
            "coverage": json.dumps(dict(coverage or {}), sort_keys=True, default=str),
            "supersedes": str(current["id"]) if current else None,
            "created": _now(),
        },
    )
    return {
        "id": row_id,
        "artifact_id": artifact_id,
        "tenant_id": tenant_id,
        "artifact_sha256": str(artifact_sha256).lower(),
        "verdict_version": version,
        "state": target.value,
    }


def bind_decision(
    db,
    *,
    tenant_id: str,
    artifact_id: str,
    decision_kind: str,
    decision_id: str,
) -> dict[str, Any]:
    """Bind a decision to the exact current clean verdict."""
    current = db.execute(
        text(
            "SELECT id, artifact_sha256, verdict_version, state "
            "FROM artifact_security_verdicts WHERE tenant_id=:tenant AND artifact_id=:artifact "
            "ORDER BY verdict_version DESC LIMIT 1"
        ),
        {"tenant": tenant_id, "artifact": artifact_id},
    ).mappings().first()
    if not current or str(current["state"]) != ArtifactState.CLEAN.value:
        raise ValueError("artifact_not_clean")
    binding_id = uuid.uuid4().hex
    db.execute(
        text(
            "INSERT INTO artifact_decision_bindings "
            "(id, tenant_id, artifact_id, artifact_sha256, verdict_id, verdict_version, "
            " decision_kind, decision_id, status, created_at) "
            "VALUES (:id,:tenant,:artifact,:sha,:verdict,:version,:kind,:decision,'active',:created)"
        ),
        {
            "id": binding_id,
            "tenant": tenant_id,
            "artifact": artifact_id,
            "sha": current["artifact_sha256"],
            "verdict": current["id"],
            "version": current["verdict_version"],
            "kind": decision_kind,
            "decision": decision_id,
            "created": _now(),
        },
    )
    return {"id": binding_id, "artifact_id": artifact_id, "verdict_version": int(current["verdict_version"])}


def evaluate_bound_artifacts(db, *, tenant_id: str, artifact_ids: Sequence[str]) -> ArtifactAuthorityResult:
    ids = tuple(dict.fromkeys(str(x) for x in artifact_ids if str(x).strip()))
    if not ids:
        return ArtifactAuthorityResult(False, "artifact_binding_required")
    rows = db.execute(
        text(
            "SELECT v.artifact_id, v.state FROM artifact_security_verdicts v "
            "JOIN (SELECT artifact_id, MAX(verdict_version) AS max_version "
            "      FROM artifact_security_verdicts WHERE tenant_id=:tenant GROUP BY artifact_id) latest "
            "ON latest.artifact_id=v.artifact_id AND latest.max_version=v.verdict_version "
            "WHERE v.tenant_id=:tenant"
        ),
        {"tenant": tenant_id},
    ).mappings().all()
    states = {str(row["artifact_id"]): str(row["state"]) for row in rows}
    missing = [artifact_id for artifact_id in ids if artifact_id not in states]
    blocked = [f"{artifact_id}:{states.get(artifact_id, 'missing')}" for artifact_id in ids if states.get(artifact_id) != "clean"]
    if missing:
        return ArtifactAuthorityResult(False, "artifact_binding_not_found", ids, tuple(missing))
    if blocked:
        return ArtifactAuthorityResult(False, "artifact_verdict_not_clean", ids, tuple(blocked))
    return ArtifactAuthorityResult(True, "all_bound_artifacts_clean", ids)


def invalidate_bindings_for_late_verdict(db, *, tenant_id: str, artifact_id: str, reason: str) -> dict[str, list[str]]:
    """Invalidate active derivations; executed bindings become incidents, not fake rollbacks."""
    rows = db.execute(
        text(
            "SELECT id, decision_kind, decision_id, status FROM artifact_decision_bindings "
            "WHERE tenant_id=:tenant AND artifact_id=:artifact AND status IN ('active','queued','executed')"
        ),
        {"tenant": tenant_id, "artifact": artifact_id},
    ).mappings().all()
    invalidated: list[str] = []
    incidents: list[str] = []
    for row in rows:
        if str(row["status"]) == "executed":
            incident_id = uuid.uuid4().hex
            db.execute(
                text(
                    "INSERT INTO artifact_security_incidents "
                    "(id, tenant_id, artifact_id, binding_id, reason, status, created_at) "
                    "VALUES (:id,:tenant,:artifact,:binding,:reason,'open',:created)"
                ),
                {"id": incident_id, "tenant": tenant_id, "artifact": artifact_id,
                 "binding": row["id"], "reason": reason, "created": _now()},
            )
            incidents.append(incident_id)
            continue
        db.execute(
            text("UPDATE artifact_decision_bindings SET status='invalidated', invalidated_at=:at, invalidation_reason=:reason WHERE id=:id"),
            {"at": _now(), "reason": reason, "id": row["id"]},
        )
        invalidated.append(str(row["id"]))
    return {"invalidated_binding_ids": invalidated, "incident_ids": incidents}
