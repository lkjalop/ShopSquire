"""Persistence boundary for an already-computed semantic evidence decision.

Interpretation, evidence normalization, and requirement compilation happen
upstream.  This module receives their immutable projections and owns only case
identity plus durable optimistic persistence.  It never computes fit or grants
catalog/commercial authority.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticBeliefPersistenceCommand:
    tenant_id: str
    uid: str
    session_epoch: str
    trace_id: str | None
    prior_case_anchor: Mapping[str, Any]
    requested_quantity: int | None
    budget_scope: str | None
    total_budget_cents: int | None
    currency: str
    semantic_decision: Mapping[str, Any]
    accepted_evidence: Sequence[Mapping[str, Any]]
    compiled_requirements: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class SemanticBeliefPersistenceResult:
    case_id: str
    projection: dict[str, Any]


def semantic_case_id(command: SemanticBeliefPersistenceCommand) -> str:
    retained = str(command.prior_case_anchor.get("case_id") or "").strip()
    if retained:
        return retained
    material = (
        f"{command.tenant_id}|{command.uid}|{command.session_epoch}"
    ).encode("utf-8")
    return "semantic-" + hashlib.sha256(material).hexdigest()[:24]


def persist_computed_semantic_belief(
    db: Any,
    command: SemanticBeliefPersistenceCommand,
) -> SemanticBeliefPersistenceResult:
    """Persist computed evidence without reinterpreting or authorizing it."""

    case_id = semantic_case_id(command)
    try:
        from src.app.services.conversation_case_state import ensure_case_state
        from src.app.services.semantic_belief_state import persist_semantic_belief

        ensure_case_state(
            db,
            tenant_id=command.tenant_id,
            case_id=case_id,
            session_epoch=command.session_epoch,
            subject_ref=hashlib.sha256(
                f"{command.tenant_id}|{command.uid}".encode("utf-8")
            ).hexdigest(),
            authoritative_anchor={
                "kind": "semantic_qualification",
                "quantity": command.requested_quantity,
                "budget": {
                    "scope": command.budget_scope,
                    "total_cents": command.total_budget_cents,
                    "currency": command.currency,
                },
            },
        )
        persisted = persist_semantic_belief(
            db,
            tenant_id=command.tenant_id,
            case_id=case_id,
            session_epoch=command.session_epoch,
            semantic_decision=dict(command.semantic_decision),
            accepted_evidence=[dict(item) for item in command.accepted_evidence],
            compiled_requirements=[
                dict(item) for item in command.compiled_requirements
            ],
            trace_id=command.trace_id,
        )
        return SemanticBeliefPersistenceResult(
            case_id=case_id,
            projection=dict(persisted),
        )
    except Exception as exc:
        logger.warning(
            "semantic belief persistence failed for trace %s: %s",
            command.trace_id,
            type(exc).__name__,
        )
        return SemanticBeliefPersistenceResult(
            case_id=case_id,
            projection={
                "status": "persistence_failed",
                "persisted": False,
                "error_type": type(exc).__name__,
            },
        )


__all__ = [
    "SemanticBeliefPersistenceCommand",
    "SemanticBeliefPersistenceResult",
    "persist_computed_semantic_belief",
    "semantic_case_id",
]
