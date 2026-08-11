"""Canonical workload qualification reducer and adversarial critic.

This module is deliberately independent of product verticals and language models.
It reduces already-authorized requirement/capability rows into one decision object,
then checks the object for authority and honesty violations before narration.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.infrastructure_alternative_projection import (
    InfrastructureAlternativeProjection,
    project_infrastructure_alternatives,
)


RowVerdict = Literal[
    "meets_minimum",
    "meets_recommended",
    "below_minimum",
    "unknown",
    "contested",
    "not_applicable",
]
OverallDecision = Literal[
    "not_qualified",
    "conditional",
    "qualified_for_stated_scope",
    "over_spec_for_stated_scope",
    "unresolved",
]


class WorkloadContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["workload-contract-v1"] = "workload-contract-v1"
    desired_outcome: str = Field(default="", max_length=500)
    artefact_name: str | None = Field(default=None, max_length=160)
    artefact_version: str | None = Field(default=None, max_length=80)
    execution_shape: Literal["local", "remote_client", "hybrid", "cloud", "unresolved"] = "unresolved"
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)
    deadline_days: int | None = Field(default=None, ge=0, le=3650)
    budget_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    scale_inputs: dict[str, Any] = Field(default_factory=dict)
    target_inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    material_unknowns: list[str] = Field(default_factory=list, max_length=12)
    surviving_hypothesis_ids: list[str] = Field(default_factory=list, max_length=5)


class ProductConfigurationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=160)
    identifier_type: str = Field(default="unresolved", max_length=80)
    identifier: str = Field(default="", max_length=240)
    configuration_hash: str | None = Field(default=None, max_length=128)
    form_factor: Literal[
        "laptop", "mobile_workstation", "desktop", "fixed_workstation",
        "server", "cloud", "unknown",
    ] = "unknown"

    @property
    def exact(self) -> bool:
        return bool(
            self.identifier
            and self.identifier_type not in {"unresolved", "title", "family_identifier", "model"}
            and self.configuration_hash
            and self.form_factor != "unknown"
        )


class FitLedgerRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_key: str = Field(min_length=1, max_length=80)
    attribute_label: str = Field(min_length=1, max_length=120)
    requirement_class: Literal["minimum", "recommended", "target", "optimal"] = "minimum"
    required: list[list[Any]] = Field(default_factory=list, max_length=8)
    required_text: str = Field(default="not recorded", max_length=240)
    observed: Any = None
    observed_text: str = Field(default="not recorded", max_length=240)
    verdict: RowVerdict
    verification_status: Literal["verified", "unverified"] = "unverified"
    claim_class: Literal["attested", "derived", "behavioral", "catalog_observation"] = "catalog_observation"
    requirement_claim_ids: list[str] = Field(default_factory=list, max_length=8)
    capability_claim_ids: list[str] = Field(default_factory=list, max_length=8)
    scope_caveat: str | None = Field(default=None, max_length=500)
    artefact_name: str | None = Field(default=None, max_length=160)
    artefact_version: str | None = Field(default=None, max_length=80)
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    resolver: str | None = Field(default=None, max_length=160)


class CriticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pass", "blocked"]
    violations: list[str] = Field(default_factory=list, max_length=32)
    checked_invariants: list[str] = Field(default_factory=list, max_length=32)


class WorkloadDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["workload-decision-v1"] = "workload-decision-v1"
    decision_id: str
    workload: WorkloadContract
    product: ProductConfigurationIdentity
    fit_ledger: list[FitLedgerRow] = Field(default_factory=list, max_length=64)
    compatibility_status: Literal["passes", "fails", "partial", "unknown"]
    performance_status: Literal["verified", "inferred", "unknown", "not_requested"]
    scale_status: Literal["resolved", "partial", "unresolved"]
    overall_decision: OverallDecision
    qualification_scope: Literal["none", "bounded_requirements", "complete_stated_scope"]
    budget_status: Literal["within", "over", "unknown"] = "unknown"
    availability_status: Literal["available", "unavailable", "unknown"] = "unknown"
    infrastructure_alternatives: InfrastructureAlternativeProjection
    authorized_narration_blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    critic: CriticResult


def configuration_hash(*, sku: str, specs: Mapping[str, Any], form_factor: str) -> str:
    """Stable configuration identity over decision-material catalog facts."""
    material = {
        "sku": str(sku or "").strip(),
        "form_factor": str(form_factor or "unknown").strip().lower(),
        "specs": {
            str(key): specs[key]
            for key in sorted(specs)
            if str(key) in {
                "manufacturer_part_number", "mpn", "machine_type_model", "mtm", "gtin",
                "cpu", "cpu_model", "cpu_cores", "ram_gb", "storage_gb", "gpu",
                "gpu_model", "gpu_vram_gb", "gpu_tgp_w", "operating_system", "os_edition",
            }
        },
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _critic(
    *,
    workload: WorkloadContract,
    product: ProductConfigurationIdentity,
    rows: Sequence[FitLedgerRow],
    overall: OverallDecision,
) -> CriticResult:
    checked = [
        "unknown_not_promoted_to_pass",
        "unverified_requirement_cannot_fail",
        "qualified_requires_exact_configuration",
        "qualified_requires_artefact_identity",
        "claim_references_retained",
        "scope_caveats_retained",
    ]
    violations: list[str] = []
    for row in rows:
        if row.verdict in {"meets_minimum", "meets_recommended"} and row.observed is None:
            violations.append(f"unknown_promoted_to_pass:{row.attribute_key}")
        if row.verdict == "below_minimum" and row.verification_status != "verified":
            violations.append(f"unverified_requirement_failed_product:{row.attribute_key}")
        if row.verdict not in {"unknown", "not_applicable"} and not row.requirement_claim_ids:
            violations.append(f"requirement_claim_reference_missing:{row.attribute_key}")
        if row.claim_class == "attested" and row.observed is not None and not row.capability_claim_ids:
            violations.append(f"attested_capability_reference_missing:{row.attribute_key}")
    if overall in {"qualified_for_stated_scope", "over_spec_for_stated_scope"}:
        if not product.exact:
            violations.append("qualified_without_exact_product_configuration")
        if not workload.artefact_name:
            violations.append("qualified_without_named_artefact")
    return CriticResult(
        status="blocked" if violations else "pass",
        violations=list(dict.fromkeys(violations))[:32],
        checked_invariants=checked,
    )


def reduce_workload_decision(
    *,
    workload: WorkloadContract,
    product: ProductConfigurationIdentity,
    rows: Sequence[FitLedgerRow],
    behavioral_evidence: Sequence[Mapping[str, Any]] = (),
    budget_status: Literal["within", "over", "unknown"] = "unknown",
    availability_status: Literal["available", "unavailable", "unknown"] = "unknown",
    cheaper_complete_match_exists: bool = False,
) -> WorkloadDecision:
    """Reduce authorized rows. The critic can only make the result less authoritative."""
    bounded_rows = list(rows)[:64]
    has_failure = any(row.verdict == "below_minimum" for row in bounded_rows)
    has_gap = any(row.verdict in {"unknown", "contested"} for row in bounded_rows)
    unresolved_workload = bool(
        not workload.artefact_name
        or len(workload.surviving_hypothesis_ids) > 1
        or (not bounded_rows and workload.material_unknowns)
    )
    if unresolved_workload:
        overall: OverallDecision = "unresolved"
    elif has_failure:
        overall = "not_qualified"
    elif has_gap or workload.material_unknowns or not bounded_rows:
        overall = "conditional"
    elif cheaper_complete_match_exists and budget_status != "over":
        overall = "over_spec_for_stated_scope"
    else:
        overall = "qualified_for_stated_scope"

    compatibility = (
        "fails" if has_failure
        else "partial" if has_gap or not bounded_rows
        else "passes"
    )
    exact_behavior = any(str(item.get("evidence_distance")) == "exact" for item in behavioral_evidence)
    inferred_behavior = any(behavioral_evidence) and not exact_behavior
    performance = "verified" if exact_behavior else "inferred" if inferred_behavior else "unknown"
    scale = (
        "unresolved" if workload.material_unknowns
        else "resolved" if workload.scale_inputs or not workload.material_unknowns
        else "partial"
    )
    scope = (
        "none" if overall == "unresolved" or not bounded_rows
        else "complete_stated_scope" if not has_gap and not workload.material_unknowns
        else "bounded_requirements"
    )
    critic = _critic(workload=workload, product=product, rows=bounded_rows, overall=overall)
    if critic.status == "blocked" and overall in {
        "qualified_for_stated_scope", "over_spec_for_stated_scope"
    }:
        overall = "conditional"
        scope = "bounded_requirements"

    verdict_label = {
        "not_qualified": "Not qualified for the stated scope",
        "conditional": "Conditional — material evidence remains",
        "qualified_for_stated_scope": "Qualified for the stated scope",
        "over_spec_for_stated_scope": "Over-spec for the stated scope",
        "unresolved": "Workload unresolved — no product qualification",
    }[overall]
    failures = [row.attribute_label for row in bounded_rows if row.verdict == "below_minimum"]
    unknowns = [row.attribute_label for row in bounded_rows if row.verdict in {"unknown", "contested"}]
    verified_minimums = [
        row.attribute_label for row in bounded_rows
        if row.verdict == "meets_minimum" and row.verification_status == "verified"
    ]
    verified_headroom = [
        row.attribute_label for row in bounded_rows
        if row.verdict == "meets_recommended" and row.verification_status == "verified"
    ]
    blocks: list[dict[str, Any]] = [
        {"block": "verdict", "text": verdict_label, "claim_refs": []},
        {
            "block": "scope",
            "text": workload.desired_outcome or workload.artefact_name or "Buyer requirements",
            "claim_refs": [],
        },
    ]
    if verified_minimums:
        blocks.append({
            "block": "verified_strengths",
            "items": list(dict.fromkeys(verified_minimums))[:8],
            "text": "Verified against the accepted minimum for: "
            + ", ".join(dict.fromkeys(verified_minimums)),
            "claim_refs": list(dict.fromkeys(
                claim_id
                for row in bounded_rows
                if row.verdict == "meets_minimum" and row.verification_status == "verified"
                for claim_id in row.requirement_claim_ids + row.capability_claim_ids
            )),
        })
    if verified_headroom:
        blocks.append({
            "block": "verified_headroom",
            "items": list(dict.fromkeys(verified_headroom))[:8],
            "text": "Verified recommended headroom for: "
            + ", ".join(dict.fromkeys(verified_headroom)),
            "claim_refs": list(dict.fromkeys(
                claim_id
                for row in bounded_rows
                if row.verdict == "meets_recommended" and row.verification_status == "verified"
                for claim_id in row.requirement_claim_ids + row.capability_claim_ids
            )),
        })
    if failures:
        blocks.append({"block": "failures", "items": failures, "claim_refs": [
            claim_id for row in bounded_rows if row.verdict == "below_minimum"
            for claim_id in row.requirement_claim_ids + row.capability_claim_ids
        ]})
    if unknowns or workload.material_unknowns:
        blocks.append({
            "block": "unknowns",
            "items": list(dict.fromkeys(unknowns + workload.material_unknowns))[:12],
            "claim_refs": [],
        })
    ledger_gaps = [
        {
            "attribute_key": row.attribute_key,
            "attribute_label": row.attribute_label,
        }
        for row in bounded_rows
        if row.verdict in {"unknown", "contested"}
    ]
    if ledger_gaps:
        blocks.append({
            "block": "ledger_gaps",
            "items": ledger_gaps,
            "claim_refs": list(dict.fromkeys(
                claim_id
                for row in bounded_rows
                if row.verdict in {"unknown", "contested"}
                for claim_id in row.requirement_claim_ids + row.capability_claim_ids
            )),
        })
    if budget_status == "over":
        # Budget status is a reducer-owned commercial fact.  It needs no evidence
        # claim reference, but it must be made available to every narrator so an
        # over-budget product cannot be described without the conflict.
        blocks.append({
            "block": "budget_conflict",
            "status": "over",
            "text": "This configuration exceeds the buyer's budget ceiling",
            "claim_refs": [],
        })
    if availability_status == "unavailable":
        blocks.append({
            "block": "availability_conflict",
            "status": "unavailable",
            "text": "This exact configuration is not currently verified as available",
            "claim_refs": [],
        })
    return WorkloadDecision(
        decision_id="wd-" + hashlib.sha256(
            f"{product.sku}|{product.configuration_hash}|{workload.model_dump_json()}".encode()
        ).hexdigest()[:20],
        workload=workload,
        product=product,
        fit_ledger=bounded_rows,
        compatibility_status=compatibility,
        performance_status=performance,
        scale_status=scale,
        overall_decision=overall,
        qualification_scope=scope,
        budget_status=budget_status,
        availability_status=availability_status,
        infrastructure_alternatives=project_infrastructure_alternatives(
            desired_outcome=workload.desired_outcome,
            unresolved_inputs=workload.material_unknowns,
        ),
        authorized_narration_blocks=blocks,
        critic=critic,
    )


def deterministic_narration(decision: WorkloadDecision) -> str:
    """Always-available narration assembled only from the authorized decision."""
    verdict = str(decision.authorized_narration_blocks[0].get("text") or "Decision unavailable")
    scope = decision.workload.desired_outcome or decision.workload.artefact_name or "the stated workload"
    parts = [f"{verdict}: {scope}."]
    verified_minimums = [
        row.attribute_label for row in decision.fit_ledger
        if row.verdict == "meets_minimum" and row.verification_status == "verified"
    ]
    verified_headroom = [
        row.attribute_label for row in decision.fit_ledger
        if row.verdict == "meets_recommended" and row.verification_status == "verified"
    ]
    failures = [row.attribute_label for row in decision.fit_ledger if row.verdict == "below_minimum"]
    gaps = [row.attribute_label for row in decision.fit_ledger if row.verdict in {"unknown", "contested"}]
    gaps.extend(decision.workload.material_unknowns)
    if verified_minimums:
        parts.append(
            "Verified against the accepted minimum for: "
            + ", ".join(dict.fromkeys(verified_minimums)) + "."
        )
    if verified_headroom:
        parts.append(
            "Verified recommended headroom for: "
            + ", ".join(dict.fromkeys(verified_headroom)) + "."
        )
    if failures:
        parts.append("Below the accepted minimum: " + ", ".join(dict.fromkeys(failures)) + ".")
    if gaps:
        parts.append("Still unresolved: " + ", ".join(dict.fromkeys(gaps)) + ".")
    if decision.budget_status == "over":
        parts.append("This configuration exceeds the buyer's budget ceiling.")
    if decision.availability_status == "unavailable":
        parts.append("This exact configuration is not currently verified as available.")
    if decision.performance_status == "unknown":
        parts.append("Behavioral performance is not verified for this exact configuration.")
    if decision.critic.status == "blocked":
        parts.append("The evidence critic blocked a stronger qualification.")
    return " ".join(parts)
