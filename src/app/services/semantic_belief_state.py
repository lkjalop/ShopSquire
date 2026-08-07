"""Durable, governed belief state for unfamiliar or ambiguous buyer workloads.

This module stores an inspectable semantic state, not model chain-of-thought and not
an uncalibrated Bayesian posterior.  Model confidence, evidence coverage, conflicts,
and deterministic authorization remain separate fields so the trace cannot imply
statistical or commercial authority that the platform has not established.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import text


_MAX_HYPOTHESES = 5
_MAX_UNKNOWNS = 8
_MAX_EVIDENCE = 24
_MAX_REQUIREMENTS = 32
_MAX_HISTORY = 20


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _bounded_confidence(value: Any) -> float:
    try:
        return round(max(0.0, min(float(value), 1.0)), 6)
    except (TypeError, ValueError):
        return 0.0


def _snapshot(belief: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "revision": int(belief.get("revision") or 0),
        "generation": int(belief.get("generation") or 1),
        "goal": _bounded_text(belief.get("goal"), 500),
        "status": _bounded_text(belief.get("status"), 60),
        "trace_id": _bounded_text(belief.get("trace_id"), 120) or None,
        "observed_at": _bounded_text(belief.get("observed_at"), 80),
        "hypothesis_ids": [
            _bounded_text(row.get("hypothesis_id"), 60)
            for row in list(belief.get("hypotheses") or [])[:_MAX_HYPOTHESES]
            if isinstance(row, Mapping)
        ],
    }


def _normalize_evidence(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for row in list(rows)[:_MAX_EVIDENCE]:
        if not isinstance(row, Mapping):
            continue
        evidence.append({
            "claim_type": _bounded_text(row.get("claim_type"), 80) or None,
            "claim_status": _bounded_text(
                row.get("claim_status") or row.get("status"), 40
            ) or "unverified",
            "citation_id": _bounded_text(row.get("citation_id"), 200) or None,
            "source_id": _bounded_text(row.get("source_id"), 160) or None,
            "source_record_id": _bounded_text(row.get("source_record_id"), 240) or None,
            "observed_at": _bounded_text(row.get("observed_at"), 80) or None,
        })
    return evidence


def _normalize_requirements(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for row in list(rows)[:_MAX_REQUIREMENTS]:
        if not isinstance(row, Mapping):
            continue
        key = _bounded_text(row.get("attribute_key"), 80)
        operator = _bounded_text(row.get("operator"), 12)
        if not key or not operator:
            continue
        requirements.append({
            "attribute_key": key,
            "operator": operator,
            "value": row.get("value"),
            "unit": _bounded_text(row.get("unit"), 40) or None,
            "source_claim_ids": [
                _bounded_text(value, 240)
                for value in list(row.get("source_claim_ids") or [])[:8]
                if _bounded_text(value, 240)
            ],
            "authority": "accepted_evidence",
        })
    return requirements


def merge_semantic_belief(
    *,
    prior: Mapping[str, Any] | None,
    semantic_decision: Mapping[str, Any],
    accepted_evidence: Sequence[Mapping[str, Any]],
    compiled_requirements: Sequence[Mapping[str, Any]],
    trace_id: str | None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Merge one authorized semantic observation into a bounded revision.

    Hypothesis confidence remains the model's proposal. Evidence support is a
    deterministic count over typed claim coverage; neither field authorizes a SKU.
    """
    prior_belief = dict(prior or {})
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    goal = _bounded_text(semantic_decision.get("desired_outcome"), 500)
    prior_goal = _bounded_text(prior_belief.get("goal"), 500)
    supersedes = bool(prior_belief and goal and prior_goal and goal != prior_goal)
    generation = int(prior_belief.get("generation") or 1) + (1 if supersedes else 0)
    revision = int(prior_belief.get("revision") or 0) + 1

    evidence = _normalize_evidence(accepted_evidence)
    verified_types = {
        str(row.get("claim_type"))
        for row in evidence
        if row.get("claim_type") and row.get("claim_status") == "verified"
    }
    conflicting_types = {
        str(row.get("claim_type"))
        for row in evidence
        if row.get("claim_type") and row.get("claim_status") == "contradictory"
    }
    hypotheses: list[dict[str, Any]] = []
    for raw in list(semantic_decision.get("workload_hypotheses") or [])[:_MAX_HYPOTHESES]:
        if not isinstance(raw, Mapping):
            continue
        matched = sorted({
            _bounded_text(value, 80)
            for value in list(raw.get("matched_claim_types") or [])
            if _bounded_text(value, 80)
        } & verified_types)
        missing = sorted({
            _bounded_text(value, 80)
            for value in list(raw.get("missing_claim_types") or [])
            if _bounded_text(value, 80)
        })
        required = len(set(matched) | set(missing))
        conflicts = sorted((set(matched) | set(missing)) & conflicting_types)
        hypotheses.append({
            "hypothesis_id": _bounded_text(raw.get("hypothesis_id"), 60),
            "label": _bounded_text(raw.get("label"), 160),
            "model_confidence": _bounded_confidence(raw.get("confidence")),
            "evidence_support": {
                "matched": len(matched),
                "required": required,
                "ratio": round(len(matched) / required, 6) if required else 0.0,
            },
            "matched_claim_types": matched,
            "missing_claim_types": missing,
            "conflicting_claim_types": conflicts,
            "evidence_coverage": _bounded_text(raw.get("evidence_coverage"), 40),
            "authorization": "proposed",
        })

    unknowns = []
    for raw in list(semantic_decision.get("material_unknowns") or [])[:_MAX_UNKNOWNS]:
        if not isinstance(raw, Mapping):
            continue
        unknowns.append({
            "unknown_id": _bounded_text(raw.get("unknown_id"), 80),
            "description": _bounded_text(raw.get("description"), 240),
            "resolution_source": _bounded_text(raw.get("resolution_source"), 20),
            "material": bool(raw.get("material", True)),
        })

    history = list(prior_belief.get("history") or [])
    if prior_belief:
        history.append(_snapshot(prior_belief))
    history = history[-_MAX_HISTORY:]
    requirements = _normalize_requirements(compiled_requirements)
    status = "qualified" if (
        semantic_decision.get("catalog_authority") == "permitted" and requirements
    ) else "unresolved"
    result = {
        "contract_version": "semantic-belief-v1",
        "revision": revision,
        "generation": generation,
        "goal": goal or prior_goal,
        "model_interpretation_confidence": _bounded_confidence(
            semantic_decision.get("interpretation_confidence")
        ),
        "status": status,
        "catalog_authority": _bounded_text(
            semantic_decision.get("catalog_authority"), 20
        ) or "blocked",
        "hypotheses": hypotheses,
        "material_unknowns": unknowns,
        "accepted_evidence": evidence,
        "compiled_requirements": requirements,
        "trace_id": _bounded_text(trace_id, 120) or None,
        "observed_at": timestamp,
        "history": history,
    }
    if supersedes:
        result["supersedes_revision"] = int(prior_belief.get("revision") or 0)
    return result


def persist_semantic_belief(
    db,
    *,
    tenant_id: str,
    case_id: str,
    session_epoch: str,
    semantic_decision: Mapping[str, Any],
    accepted_evidence: Sequence[Mapping[str, Any]],
    compiled_requirements: Sequence[Mapping[str, Any]],
    trace_id: str | None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Persist one revision with an optimistic version check.

    The caller must create the case anchor first. A concurrent writer produces a
    typed conflict instead of silently overwriting another buyer turn.
    """
    if not all(str(value or "").strip() for value in (tenant_id, case_id, session_epoch)):
        raise ValueError("semantic_belief_scope_required")
    row = db.execute(
        text(
            "SELECT id,version,state_json FROM conversation_case_state "
            "WHERE tenant_id=:tenant AND case_id=:case_id AND session_epoch=:epoch"
        ),
        {"tenant": tenant_id, "case_id": case_id, "epoch": session_epoch},
    ).first()
    if not row:
        return {"status": "case_not_found", "persisted": False}
    state = json.loads(row[2]) if row[2] else {}
    prior = state.get("semantic_belief") if isinstance(state, dict) else None
    if (
        isinstance(prior, Mapping)
        and trace_id
        and str(prior.get("trace_id") or "") == str(trace_id)
    ):
        return {
            "status": "already_persisted",
            "persisted": True,
            "belief": dict(prior),
        }
    belief = merge_semantic_belief(
        prior=prior,
        semantic_decision=semantic_decision,
        accepted_evidence=accepted_evidence,
        compiled_requirements=compiled_requirements,
        trace_id=trace_id,
        observed_at=observed_at,
    )
    state["semantic_belief"] = belief
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    updated = db.execute(
        text(
            "UPDATE conversation_case_state SET state_json=:state,version=version+1,"
            "updated_at=:timestamp WHERE id=:id AND version=:version"
        ),
        {
            "state": json.dumps(state, sort_keys=True, separators=(",", ":")),
            "timestamp": timestamp,
            "id": row[0],
            "version": int(row[1]),
        },
    )
    if int(updated.rowcount or 0) != 1:
        db.rollback()
        return {"status": "version_conflict", "persisted": False}
    db.commit()
    return {"status": "persisted", "persisted": True, "belief": belief}
