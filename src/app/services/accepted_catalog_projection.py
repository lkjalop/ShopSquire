"""Project accepted provisional constraints onto exact catalog configurations.

This adapter is intentionally vocabulary-light: it compares typed attributes and lets
the canonical workload reducer and shelf reducer own fit semantics and presentation.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import select

from src.app.models.orm import ProductConfiguration
from src.app.services.recommendation_core.product_shelves import (
    ProductShelfProjection, ShelfCandidateInput, build_product_shelves,
)
from src.app.services.recommendation_core.workload_decision import (
    FitLedgerRow, ProductConfigurationIdentity, WorkloadContract,
    configuration_hash, reduce_workload_decision,
)


_CAPABILITY_FIELDS = {
    "ram_gb": "ram_installed_gb",
    "storage_gb": "storage_gb",
    "gpu_vram_gb": "gpu_vram_gb",
    "gpu_class": "gpu_class",
    "operating_system": "os_edition",
}


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _verdict(claim: Mapping[str, Any], observed: Any) -> str:
    if observed is None:
        return "unknown"
    operator = str(claim.get("operator") or "=")
    expected = claim.get("value")
    if operator == ">=":
        try:
            return "meets_minimum" if float(observed) >= float(expected) else "below_minimum"
        except (TypeError, ValueError):
            return "unknown"
    if operator == "one_of":
        options = expected if isinstance(expected, list) else [expected]
        return "meets_minimum" if any(_normalized(option) in _normalized(observed) for option in options) else "below_minimum"
    if operator == "conditional" and not claim.get("condition"):
        return "not_applicable"
    return "meets_minimum" if _normalized(expected) in _normalized(observed) else "below_minimum"


def _identity(row: ProductConfiguration) -> ProductConfigurationIdentity:
    canonical_form = "laptop" if row.form_factor == "laptop" else "desktop"
    return ProductConfigurationIdentity(
        sku=row.sku, identifier_type="mpn", identifier=row.mpn or "",
        configuration_hash=row.configuration_hash or configuration_hash(
            sku=row.sku, form_factor=canonical_form, specs={
                "mpn": row.mpn, "ram_gb": row.ram_installed_gb,
                "storage_gb": row.storage_gb, "gpu_vram_gb": row.gpu_vram_gb,
                "gpu_tgp_w": row.gpu_tgp_w, "os_edition": row.os_edition,
            },
        ),
        form_factor=canonical_form,
    )


def _decision(
    row: ProductConfiguration,
    claims: Sequence[Mapping[str, Any]],
    *,
    scope_id: str,
    desired_outcome: str,
    budget_cents: int | None,
):
    identity = _identity(row)
    ledger: list[FitLedgerRow] = []
    for claim in claims:
        attribute = str(claim.get("attribute") or "")
        field = _CAPABILITY_FIELDS.get(attribute)
        observed = getattr(row, field, None) if field else None
        verdict = _verdict(claim, observed)
        ledger.append(FitLedgerRow(
            attribute_key=attribute,
            attribute_label=attribute.replace("_", " "),
            requirement_class=str(claim.get("requirement_class") or "minimum"),
            required=[[str(claim.get("operator") or "="), claim.get("value")]],
            required_text=f"{claim.get('operator')} {claim.get('value')}",
            observed=observed,
            observed_text="not recorded" if observed is None else str(observed),
            verdict=verdict,
            verification_status=(
                "verified" if str(claim.get("authority_status") or "").startswith("verified")
                else "unverified"
            ),
            claim_class=str(claim.get("claim_class") or "catalog_observation"),
            requirement_claim_ids=[str(claim.get("claim_id"))],
            capability_claim_ids=[],
            scope_caveat=str(claim.get("condition") or "") or None,
            freshness_status=str(claim.get("freshness_status") or "unknown"),
        ))
    workload = WorkloadContract(
        desired_outcome=desired_outcome, artefact_name="buyer-accepted provisional scope",
        budget_cents=budget_cents, currency="AUD", surviving_hypothesis_ids=[scope_id],
        material_unknowns=["buyer-supplied requirements are not independently corroborated"],
    )
    return reduce_workload_decision(
        workload=workload, product=identity, rows=ledger,
        budget_status="over" if budget_cents is not None and row.price_cents > budget_cents else "within" if budget_cents is not None else "unknown",
    )


def project_accepted_catalog(
    db,
    *,
    accepted_claims: Sequence[Mapping[str, Any]],
    desired_outcome: str = "Buyer accepted requirements",
    budget_cents: int | None = None,
    tenant_id: str = "default",
    hypothesis_labels: Mapping[str, str] | None = None,
) -> ProductShelfProjection:
    rows = db.execute(select(ProductConfiguration).where(
        ProductConfiguration.tenant_id == tenant_id,
        ProductConfiguration.active.is_(True),
    )).scalars().all()
    conditional = [claim for claim in accepted_claims if claim.get("condition")]
    shared_claims = [claim for claim in accepted_claims if not claim.get("condition")]
    proposed_labels = {
        str(key).strip(): str(value).strip()
        for key, value in dict(hypothesis_labels or {}).items()
        if str(key).strip() and str(value).strip()
    }
    architecture_ids = sorted({f"architecture:{row.device_class}" for row in rows})
    hypothesis_ids = (
        (["conditional_scope"] if conditional else [])
        + list(proposed_labels)
        + architecture_ids
    )
    labels = {
        "shared": "Best across accepted shared needs",
        "conditional_scope": "If the stated conditional workload applies",
        **{
            scope_id: scope_id.removeprefix("architecture:").replace("_", " ").title()
            for scope_id in architecture_ids
        },
        **proposed_labels,
    }
    candidates: list[ShelfCandidateInput] = []
    for row in rows:
        identity = _identity(row)
        decisions = {
            "shared": _decision(
                row, shared_claims, scope_id="shared", desired_outcome=desired_outcome,
                budget_cents=budget_cents,
            ),
        }
        if conditional:
            decisions["conditional_scope"] = _decision(
                row, [*shared_claims, *conditional], scope_id="conditional_scope",
                desired_outcome=desired_outcome, budget_cents=budget_cents,
            )
        architecture_scope = f"architecture:{row.device_class}"
        decisions[architecture_scope] = _decision(
            row, shared_claims, scope_id=architecture_scope,
            desired_outcome=desired_outcome, budget_cents=budget_cents,
        )
        for hypothesis_id in proposed_labels:
            decisions[hypothesis_id] = _decision(
                row, shared_claims, scope_id=hypothesis_id,
                desired_outcome=desired_outcome, budget_cents=budget_cents,
            )
        known = sum(
            1 for claim in accepted_claims
            if _CAPABILITY_FIELDS.get(str(claim.get("attribute") or ""))
            and getattr(row, _CAPABILITY_FIELDS[str(claim.get("attribute"))], None) is not None
        )
        candidates.append(ShelfCandidateInput(
            product=identity, title=row.title, price_cents=row.price_cents,
            relevance_score=known / max(1, len(accepted_claims)), fit_by_scope=decisions,
        ))
    return build_product_shelves(
        candidates, hypothesis_ids=hypothesis_ids, scope_labels=labels,
        budget_cents=budget_cents,
    )


__all__ = ["project_accepted_catalog"]
