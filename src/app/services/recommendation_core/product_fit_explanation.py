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
            "observed": value,
            "observed_text": observed_text,
            "observed_source": "catalog_attribute",
            "product_evidence_refs": (
                [str(product_claim.get("source_record_id"))]
                if product_claim and product_claim.get("source_record_id") else []
            ),
            "product_evidence_verdict": product_evidence_verdict,
            "verdict": verdict,
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
    coverage_status = "partial" if qualification_scope == "bounded_requirements" else "not_assessed"
    overall = str(fit.get("overall") or "").strip() or None
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
        "material_unknowns": list(semantic.get("material_unknowns") or [])[:8],
        "commercial_authority_granted": False,
        "product_capability_evidence": product_evidence or {
            "status": "not_requested",
            "commercial_authority_granted": False,
        },
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
