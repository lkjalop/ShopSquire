"""Compile authoritative workload evidence into registry-backed predicates.

The model and connectors may propose claims.  Only this compiler can convert a
claim into a hard catalog requirement, and only when source authority,
provenance, confidence, and the attribute registry all validate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.app.services.attribute_registry import (
    defs_union,
    normalize_value,
    registered_verticals,
)
from src.app.services.recommendation_core.research_contracts import CompiledRequirement


_AUTHORITATIVE = frozenset({"official_requirements", "approved_tenant_document"})
_OPERATORS = frozenset({">=", "<=", "=", "in", "contains"})


@dataclass(frozen=True)
class CompilationResult:
    requirements: tuple[CompiledRequirement, ...]
    rejections: tuple[dict[str, Any], ...]


def compile_authoritative_requirements(
    claims: Iterable[Mapping[str, Any]],
    *,
    minimum_confidence: float = 0.80,
) -> CompilationResult:
    defs = defs_union(registered_verticals())
    accepted: list[CompiledRequirement] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(list(claims)[:64]):
        claim = raw if isinstance(raw, Mapping) else {}
        claim_id = str(claim.get("source_record_id") or claim.get("need_id") or index)[:240]

        def reject(reason: str) -> None:
            rejected.append({"claim_id": claim_id, "reason": reason})

        if str(claim.get("status") or "") != "accepted":
            reject("claim_not_accepted")
            continue
        if str(claim.get("authority") or "") not in _AUTHORITATIVE:
            reject("source_not_authoritative")
            continue
        if not str(claim.get("source_id") or "").strip() or not str(
            claim.get("source_record_id") or ""
        ).strip():
            reject("provenance_incomplete")
            continue
        if not str(claim.get("lineage_root") or "").strip():
            reject("lineage_root_missing")
            continue
        if not str(claim.get("observed_at") or "").strip():
            reject("observation_time_missing")
            continue
        try:
            confidence = float(claim.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < minimum_confidence:
            reject("confidence_below_policy")
            continue
        key = str(claim.get("attribute_key") or "").strip()
        definition = defs.get(key)
        if definition is None or definition.role not in {"fit", "regulatory"}:
            reject("attribute_not_registry_authorized")
            continue
        operator = str(claim.get("operator") or "").strip()
        if operator not in _OPERATORS:
            reject("operator_not_authorized")
            continue
        value = normalize_value(definition, claim.get("value"))
        if value is None:
            reject("value_not_registry_valid")
            continue
        accepted.append(
            CompiledRequirement(
                attribute_key=key,
                operator=operator,
                value=value,
                unit=definition.unit,
                source_claim_ids=[claim_id],
                artefact_name=(str(claim.get("artefact_name") or "").strip()[:160] or None),
                artefact_version=(str(claim.get("artefact_version") or "").strip()[:80] or None),
                requirement_class=(
                    str(claim.get("requirement_class") or "minimum").strip().lower()
                    if str(claim.get("requirement_class") or "minimum").strip().lower()
                    in {"minimum", "recommended", "target", "optimal"}
                    else "minimum"
                ),
                scope_caveat=(str(claim.get("scope_caveat") or "").strip()[:500] or None),
                source_revision=(str(claim.get("source_revision") or "").strip()[:160] or None),
                freshness_status=(
                    str(claim.get("freshness_status") or "unknown").strip().lower()
                    if str(claim.get("freshness_status") or "unknown").strip().lower()
                    in {"fresh", "stale", "unknown"}
                    else "unknown"
                ),
                verification_status="verified",
                supersedes_claim_id=(
                    str(claim.get("supersedes_claim_id") or "").strip()[:240] or None
                ),
            )
        )
    return CompilationResult(tuple(accepted), tuple(rejected))
