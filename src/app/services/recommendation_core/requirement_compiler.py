"""Compile authoritative workload evidence into registry-backed predicates.

The model and connectors may propose claims.  Only this compiler can convert a
claim into a hard catalog requirement, and only when source authority,
provenance, confidence, and the attribute registry all validate it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from src.app.services.attribute_registry import (
    load_defs,
    normalize_value,
)
from src.app.services.recommendation_core.requirement_scope import RequirementScope, scope_is_current
from src.app.services.recommendation_core.research_contracts import CompiledRequirement


_AUTHORITATIVE = frozenset({"official_requirements", "approved_tenant_document"})
_OPERATORS = {
    "quantity": frozenset({">=", "<=", "="}),
    "enum": frozenset({"=", "in"}),
    "boolean": frozenset({"="}),
    # Substring membership cannot establish identity or compatibility. Exact
    # equality is executable; richer compatibility needs a reviewed typed rule.
    "text": frozenset({"=", "in"}),
}


@dataclass(frozen=True)
class CompilationResult:
    requirements: tuple[CompiledRequirement, ...]
    rejections: tuple[dict[str, Any], ...]


def compile_authoritative_requirements(
    claims: Iterable[Mapping[str, Any]],
    *,
    minimum_confidence: float = 0.80,
    scope: RequirementScope | None = None,
) -> CompilationResult:
    scope_error = (
        "compilation_scope_unresolved" if scope is None
        else "compilation_scope_stale" if not scope_is_current(scope) else None
    )
    defs = load_defs(scope.manifest_id) if scope and not scope_error else {}
    accepted: list[CompiledRequirement] = []
    rejected: list[dict[str, Any]] = []
    for raw in list(claims)[:64]:
        claim = raw if isinstance(raw, Mapping) else {}
        # A page/provider row can support multiple predicates. Preserve the row
        # separately; predicate identity must also include its exact contents.
        identity = {key: claim.get(key) for key in (
            "source_id", "source_record_id", "source_revision", "subject_span",
            "attribute_key", "operator", "value", "unit", "requirement_class",
            "scope_caveat", "artefact_name", "artefact_version",
            "source_excerpt", "value_spans",
        )}
        claim_id = "claim-" + hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(",", ":"), default=str,
        ).encode("utf-8")).hexdigest()

        def reject(reason: str) -> None:
            rejected.append({
                "claim_id": claim_id, "reason": reason,
                "attribute_key": claim.get("attribute_key"),
                "source_record_id": claim.get("source_record_id"),
                "claim_origin": claim.get("claim_origin", "observed"),
                "source_excerpt": str(claim.get("source_excerpt") or "")[:1000] or None,
            })

        if str(claim.get("status") or "") != "accepted":
            reject("claim_not_accepted")
            continue
        if scope_error:
            reject(scope_error)
            continue
        if str(claim.get("authority") or "") not in _AUTHORITATIVE:
            reject("source_not_authoritative")
            continue
        if claim.get("claim_origin", "observed") != "observed":
            reject("derived_claim_requires_policy")
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
        if not math.isfinite(confidence) or not minimum_confidence <= confidence <= 1:
            reject("confidence_below_policy")
            continue
        key = str(claim.get("attribute_key") or "").strip()
        definition = defs.get(key)
        if definition is None:
            reject("attribute_not_applicable")
            continue
        if "fit" not in definition.allowed_uses:
            reject("attribute_not_registry_authorized")
            continue
        operator = str(claim.get("operator") or "").strip()
        if operator not in _OPERATORS.get(definition.kind, frozenset()):
            reject("operator_not_authorized")
            continue
        raw_value = claim.get("value")
        source_unit = str(claim.get("unit") or "").strip().lower()
        if source_unit:
            canonical_unit = str(definition.unit or "").lower()
            if definition.kind != "quantity" or (
                source_unit != canonical_unit and source_unit not in definition.unit_aliases
            ):
                reject("unit_not_registry_valid")
                continue
            # Structured value/unit is normalized together. Embedded-unit strings
            # remain supported when there is no separate unit field; conflicting
            # double specifications are rejected rather than guessed.
            try:
                if isinstance(raw_value, bool):
                    raise ValueError("boolean is not a quantity")
                raw_value = float(raw_value) * definition.unit_aliases.get(source_unit, 1.0)
            except (TypeError, ValueError, OverflowError):
                reject("value_not_registry_valid")
                continue
        if operator == "in":
            spans, excerpt = claim.get("value_spans"), claim.get("source_excerpt")
            if not (isinstance(raw_value, list) and 1 <= len(raw_value) <= 16
                    and isinstance(spans, list) and len(spans) == len(raw_value)
                    and isinstance(excerpt, str) and len(excerpt) <= 4000
                    and all(isinstance(item, str) and isinstance(span, list)
                            and len(span) == 2 and all(type(x) is int for x in span)
                            and 0 <= span[0] < span[1] <= len(excerpt)
                            and excerpt[span[0]:span[1]] == item
                            for item, span in zip(raw_value, spans))):
                reject("alternative_span_invalid")
                continue
            value = [normalize_value(definition, item) for item in raw_value]
            if any(item is None for item in value):
                reject("value_not_registry_valid")
                continue
        else:
            value = normalize_value(definition, raw_value)
        if isinstance(value, (int, float)) and not math.isfinite(value):
            value = None
        if value is None:
            reject("value_not_registry_valid")
            continue
        accepted.append(
            CompiledRequirement(
                attribute_key=key,
                compilation_scope=scope,
                operator=operator,
                value=value,
                unit=definition.unit,
                source_claim_ids=[claim_id],
                source_excerpt=(str(claim.get("source_excerpt"))[:4000] if claim.get("source_excerpt") else None),
                value_spans=claim.get("value_spans") if operator == "in" else [],
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
                verification_status=(
                    "verified" if claim.get("authority") == "official_requirements"
                    and claim.get("claim_origin", "observed") == "observed"
                    else "unverified"
                ),
                supersedes_claim_id=(
                    str(claim.get("supersedes_claim_id") or "").strip()[:240] or None
                ),
            )
        )
    return CompilationResult(tuple(accepted), tuple(rejected))
