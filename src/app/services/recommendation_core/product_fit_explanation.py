"""Canonical buyer-facing projection of an authorized product fit verdict.

The model may identify a workload and providers may establish requirements. This module only
projects already-authorized requirements and catalog observations; it never invents a workload
floor, benchmark, product capability, or commercial permission.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.app.services.attribute_registry import defs_union, registered_verticals


def _attribute_label(key: str) -> str:
    labels = {
        "ram_gb": "RAM",
        "gpu_vram_gb": "GPU VRAM",
        "storage_gb": "storage",
        "refresh_hz": "refresh rate",
        "cpu_cores": "CPU cores",
    }
    return labels.get(str(key), str(key).replace("_", " "))


def _format_value(value: Any, unit: str | None = None) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    suffix = f" {unit}" if unit else ""
    return f"{value}{suffix}"


def _format_required(predicates: Sequence[Sequence[Any]], unit: str | None) -> str:
    rendered: list[str] = []
    for predicate in predicates:
        if not isinstance(predicate, (list, tuple)) or len(predicate) != 2:
            continue
        operator, threshold = predicate
        rendered.append(f"{operator} {_format_value(threshold, unit)}")
    return " and ".join(rendered) or "not recorded"


def build_product_fit_explanation(
    *,
    product: Any,
    requirements: Mapping[str, Sequence[Sequence[Any]]],
    semantic_resolution: Mapping[str, Any] | None = None,
    requirement_compilation: Mapping[str, Any] | None = None,
    product_capability_evidence: Mapping[str, Any] | None = None,
    behavioral_evidence: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], str]:
    """Return the canonical explanation payload and concise grounded narration."""
    semantic = dict(semantic_resolution or {})
    compilation = dict(requirement_compilation or {})
    product_evidence = dict(product_capability_evidence or {})
    product_claims = {
        str(item.get("attribute_key")): item
        for item in list(product_evidence.get("accepted_claims") or [])[:64]
        if isinstance(item, dict) and str(item.get("attribute_key") or "").strip()
    }
    compiled = [
        item for item in list(compilation.get("compiled_requirements") or [])[:64]
        if isinstance(item, dict)
    ]
    compiled_by_key = {
        str(item.get("attribute_key")): item
        for item in compiled
        if str(item.get("attribute_key") or "").strip()
    }
    attribute_defs = defs_union(registered_verticals())
    fit = product.fit if isinstance(getattr(product, "fit", None), dict) else {}
    per_key = fit.get("per_key") if isinstance(fit.get("per_key"), dict) else {}
    observed = fit.get("observed") if isinstance(fit.get("observed"), dict) else {}
    ledger: list[dict[str, Any]] = []
    phrases: list[str] = []
    for key, raw_predicates in list(requirements.items())[:64]:
        predicates = (
            list(raw_predicates)
            if isinstance(raw_predicates, list)
            else [raw_predicates]
        )
        predicates = [list(item) for item in predicates if isinstance(item, (list, tuple))]
        compiled_row = compiled_by_key.get(str(key), {})
        source_refs = list(compiled_row.get("source_claim_ids") or [])[:8]
        definition = attribute_defs.get(str(key))
        unit = (
            str(compiled_row.get("unit") or "").strip()
            or str(getattr(definition, "unit", None) or "").strip()
            or None
        )
        value = observed.get(key)
        product_claim = product_claims.get(str(key))
        product_claim_value = product_claim.get("value") if product_claim else None
        product_evidence_verdict = None
        if product_claim:
            product_evidence_verdict = (
                "confirms_catalog"
                if str(product_claim_value) == str(value)
                else "conflicts_with_catalog"
            )
        status = per_key.get(key)
        verdict = "meets" if status is True else "fails" if status is False else "unknown"
        requirement_class = str(compiled_row.get("requirement_class") or "minimum").lower()
        verification_status = str(compiled_row.get("verification_status") or "").lower()
        if verification_status not in {"verified", "unverified"}:
            verification_status = "verified" if source_refs else "unverified"
        if product_evidence_verdict == "conflicts_with_catalog":
            decision_verdict = "contested"
        elif status is True:
            decision_verdict = (
                "meets_recommended" if requirement_class in {"recommended", "target", "optimal"}
                else "meets_minimum"
            )
        elif status is False and verification_status == "verified":
            decision_verdict = "below_minimum"
        else:
            decision_verdict = "unknown"
        required_text = _format_required(predicates, unit)
        observed_text = _format_value(value, unit) if value is not None else "not recorded"
        ledger.append({
            "attribute": str(key),
            "attribute_label": _attribute_label(str(key)),
            "required": predicates,
            "required_text": required_text,
            "requirement_source": (
                "authoritative_external_evidence"
                if source_refs else "buyer_or_authorized_workload_requirement"
            ),
            "requirement_evidence_refs": source_refs,
            "requirement_class": requirement_class,
            "verification_status": verification_status,
            "scope_caveat": compiled_row.get("scope_caveat"),
            "artefact_name": compiled_row.get("artefact_name"),
            "artefact_version": compiled_row.get("artefact_version"),
            "source_revision": compiled_row.get("source_revision"),
            "freshness_status": compiled_row.get("freshness_status") or "unknown",
            "observed": value,
            "observed_text": observed_text,
            "observed_source": "catalog_attribute",
            "product_evidence_refs": (
                [str(product_claim.get("source_record_id"))]
                if product_claim and product_claim.get("source_record_id") else []
            ),
            "product_evidence_verdict": product_evidence_verdict,
            "claim_class": (
                str(product_claim.get("claim_class") or "attested")
                if product_claim else "catalog_observation"
            ),
            "verdict": verdict,
            "decision_verdict": decision_verdict,
        })
        phrases.append(
            f"{_attribute_label(str(key))} {observed_text} "
            f"{verdict} the accepted {required_text} requirement"
        )

    workload = str(semantic.get("desired_outcome") or "").strip() or None
    has_authoritative_requirements = any(
        bool(row.get("requirement_evidence_refs")) for row in ledger
    )
    qualification_scope = (
        "bounded_requirements" if workload and has_authoritative_requirements
        else "buyer_requirements" if ledger else "ranking_only"
    )
    overall = str(fit.get("overall") or "").strip() or None
    material_unknowns = list(semantic.get("material_unknowns") or [])[:8]
    if any(row.get("verdict") == "fails" for row in ledger):
        coverage_status = "does_not_meet_accepted_requirements"
    elif not ledger:
        coverage_status = "not_assessed"
    elif any(row.get("verdict") == "unknown" for row in ledger) or material_unknowns:
        coverage_status = "partial"
    elif qualification_scope == "bounded_requirements":
        coverage_status = "meets_accepted_requirements_only"
    else:
        coverage_status = "not_assessed"
    payload = {
        "sku": str(getattr(product, "sku", "") or ""),
        "name": str(getattr(product, "title", "") or ""),
        "workload_summary": workload,
        "verdict": overall,
        "qualification_scope": qualification_scope,
        "coverage_status": coverage_status,
        "verified_requirement_count": len(ledger),
        "basis": list(getattr(product, "why", None) or [])[:3],
        "fit_ledger": ledger,
        "material_unknowns": material_unknowns,
        "commercial_authority_granted": False,
        "product_capability_evidence": product_evidence or {
            "status": "not_requested",
            "commercial_authority_granted": False,
        },
    }

    # Canonical qualification is a separate deterministic projection. The legacy
    # `verdict`/`coverage_status` fields remain for transport compatibility while
    # new UI and narration consume this versioned object.
    try:
        from src.app.services.recommendation_core.workload_decision import (
            FitLedgerRow,
            ProductConfigurationIdentity,
            WorkloadContract,
            deterministic_narration,
            reduce_workload_decision,
        )

        artefact_rows = [row for row in ledger if row.get("artefact_name")]
        artefact_name = str((artefact_rows[0] if artefact_rows else {}).get("artefact_name") or "").strip() or None
        artefact_version = str((artefact_rows[0] if artefact_rows else {}).get("artefact_version") or "").strip() or None
        unknown_text = [
            str(item if isinstance(item, str) else item.get("label") or item.get("question") or item.get("unknown_id") or "")
            for item in material_unknowns if item
        ]
        workload_contract = WorkloadContract(
            desired_outcome=workload or "",
            artefact_name=artefact_name,
            artefact_version=artefact_version,
            execution_shape=str(semantic.get("execution_shape") or "unresolved")
            if str(semantic.get("execution_shape") or "unresolved")
            in {"local", "remote_client", "hybrid", "cloud", "unresolved"}
            else "unresolved",
            quantity=semantic.get("quantity") if isinstance(semantic.get("quantity"), int) else None,
            deadline_days=(
                semantic.get("deadline_days")
                if isinstance(semantic.get("deadline_days"), int) else None
            ),
            budget_cents=(
                semantic.get("budget_cents")
                if isinstance(semantic.get("budget_cents"), int) else None
            ),
            currency=(
                str(semantic.get("currency") or "").upper()
                if len(str(semantic.get("currency") or "")) == 3 else None
            ),
            scale_inputs=dict(semantic.get("scale_inputs") or {}),
            target_inputs=dict(semantic.get("target_inputs") or {}),
            constraints=dict(semantic.get("constraints") or {}),
            assumptions=[str(item) for item in list(semantic.get("assumptions") or [])[:8]],
            material_unknowns=[item for item in unknown_text if item][:12],
            surviving_hypothesis_ids=[
                str(item.get("hypothesis_id") if isinstance(item, Mapping) else item)
                for item in list(semantic.get("workload_hypotheses") or [])[:5]
                if str(item)
            ],
        )
        identity_raw = product_evidence.get("identity") if isinstance(product_evidence.get("identity"), Mapping) else {}
        product_identity = ProductConfigurationIdentity(
            sku=payload["sku"] or "unknown-sku",
            identifier_type=str(identity_raw.get("identifier_type") or "unresolved"),
            identifier=str(identity_raw.get("identifier") or ""),
            configuration_hash=str(identity_raw.get("configuration_hash") or "").strip() or None,
            form_factor=str(identity_raw.get("form_factor") or "unknown")
            if str(identity_raw.get("form_factor") or "unknown") in {"laptop", "desktop", "server", "cloud", "unknown"}
            else "unknown",
        )
        canonical_rows = [FitLedgerRow(
            attribute_key=str(row["attribute"]),
            attribute_label=str(row["attribute_label"]),
            requirement_class=str(row.get("requirement_class") or "minimum"),
            required=list(row.get("required") or []),
            required_text=str(row.get("required_text") or "not recorded"),
            observed=row.get("observed"),
            observed_text=str(row.get("observed_text") or "not recorded"),
            verdict=str(row.get("decision_verdict") or "unknown"),
            verification_status=str(row.get("verification_status") or "unverified"),
            claim_class=str(row.get("claim_class") or "catalog_observation"),
            requirement_claim_ids=[str(item) for item in row.get("requirement_evidence_refs") or []],
            capability_claim_ids=[str(item) for item in row.get("product_evidence_refs") or []],
            scope_caveat=row.get("scope_caveat"),
            artefact_name=row.get("artefact_name"),
            artefact_version=row.get("artefact_version"),
            freshness_status=str(row.get("freshness_status") or "unknown")
            if str(row.get("freshness_status") or "unknown") in {"fresh", "stale", "unknown"}
            else "unknown",
            resolver=("official product source" if row.get("observed") is None else None),
        ) for row in ledger]
        decision_object = reduce_workload_decision(
            workload=workload_contract,
            product=product_identity,
            rows=canonical_rows,
            behavioral_evidence=behavioral_evidence,
            availability_status="available" if getattr(product, "stock", None) else "unknown",
        )
        payload["workload_decision"] = decision_object.model_dump(mode="json")
        payload["decision_narration"] = deterministic_narration(decision_object)
    except Exception as exc:
        payload["workload_decision"] = {
            "schema_version": "workload-decision-v1",
            "overall_decision": "unresolved",
            "critic": {"status": "blocked", "violations": [f"decision_projection_error:{type(exc).__name__}"]},
        }

    title = payload["name"] or payload["sku"] or "This product"
    if phrases:
        purpose = f" for {workload}" if workload else ""
        narration = f"Why {title} is a candidate{purpose}: " + "; ".join(phrases) + "."
        if qualification_scope == "bounded_requirements":
            narration += (
                " This is a bounded qualification against the accepted checks above, not proof "
                "of complete workflow performance or compatibility."
            )
        if product_evidence.get("status") == "accepted":
            confirmed = sum(
                1 for row in ledger if row.get("product_evidence_verdict") == "confirms_catalog"
            )
            narration += f" Official product evidence confirms {confirmed} compared configuration fact(s)."
        elif product_evidence.get("status") in {"conflict", "rejected", "blocked"}:
            narration += " Product-source evidence did not clear validation, so it was not used as proof."
    else:
        narration = (
            f"Why {title} is shown: the authorized slate retained no capability comparison "
            "for this product, so I cannot claim verified workload fit."
        )
    return payload, narration
