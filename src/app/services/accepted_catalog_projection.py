"""Project accepted provisional constraints onto exact catalog configurations.

This adapter is intentionally vocabulary-light: it compares typed attributes and lets
the canonical workload reducer and shelf reducer own fit semantics and presentation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Any, Mapping, Sequence

from sqlalchemy import select

from src.app.models.orm import (
    ProductAvailabilityObservation,
    ProductConfiguration,
    ProductEvidenceObservation,
)
from src.app.services.recommendation_core.product_shelves import (
    AvailabilityProjection,
    EvidenceFreshnessProjection,
    ProductIdentityEvidenceProjection,
    ProductShelfProjection,
    ShelfCandidateInput,
    build_product_shelves,
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
    "gpu_tgp_w": "gpu_tgp_w",
    "ram_ceiling_gb": "ram_ceiling_gb",
    "ram_upgradeable": "ram_upgradeable",
    "warranty_type": "warranty_type",
    "warranty_years": "warranty_years",
    "device_class": "device_class",
    "form_factor": "form_factor",
    "mobility": "mobility",
}

_OBSERVATION_ALIASES = {
    "operating_system": ("operating_system", "os_edition"),
    "ram_gb": ("ram_gb", "ram_installed_gb"),
    "storage_gb": ("storage_gb",),
}
_FRESHNESS_HOURS = {"specification": 720, "price": 24, "availability": 24}


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _verdict(claim: Mapping[str, Any], observed: Any) -> str:
    from src.app.services.attribute_registry import meets

    if observed is None:
        return "unknown"
    operator = str(claim.get("operator") or "=")
    expected = claim.get("value")
    if operator in {">=", "<=", ">", "<"}:
        try:
            if isinstance(observed, bool) or isinstance(expected, bool):
                return "unknown"
            observed, expected = float(observed), float(expected)
            if not math.isfinite(observed) or not math.isfinite(expected):
                return "unknown"
        except (TypeError, ValueError, OverflowError):
            return "unknown"
    else:
        if operator == "conditional":
            if not claim.get("condition"):
                return "not_applicable"
            operator = "="
        operator = {"one_of": "in", "equals": "="}.get(operator, operator)
        if operator not in {"=", "==", "in"}:
            return "unknown"
        values = expected if isinstance(expected, list) else [expected]
        if isinstance(observed, bool) or any(isinstance(value, bool) for value in values):
            if not isinstance(observed, bool) or not all(isinstance(value, bool) for value in values):
                return "unknown"
            return "meets_minimum" if observed in values else "below_minimum"
        if not values or any(value is None or not str(value).strip() for value in values):
            return "unknown"
        observed = _normalized(observed)
        expected = [_normalized(value) for value in values] if operator == "in" else _normalized(expected)
    result = meets({"value": observed}, "value", operator, expected)
    return "unknown" if result is None else "meets_minimum" if result else "below_minimum"


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness(
    observed_at: Any,
    *,
    now: datetime,
    max_age_hours: int,
    expires_at: Any = None,
) -> str:
    observed = _as_utc(observed_at)
    if observed is None:
        return "unknown"
    if observed > now:
        return "unknown"
    expiry = _as_utc(expires_at)
    if expiry is not None:
        return "fresh" if now <= expiry else "stale"
    age_hours = (now - observed).total_seconds() / 3600
    return "fresh" if age_hours <= max_age_hours else "stale"


def _value(row: ProductEvidenceObservation) -> Any:
    payload = row.value_json if isinstance(row.value_json, dict) else {}
    return payload.get("value")


def _evidence_for_attribute(
    row: ProductConfiguration,
    attribute: str,
    observations: Sequence[ProductEvidenceObservation],
    *,
    now: datetime,
) -> dict[str, Any]:
    aliases = set(_OBSERVATION_ALIASES.get(attribute, (attribute,)))
    matching = [item for item in observations if item.attribute_key in aliases]
    superseded_ids = {item.supersedes_id for item in matching if item.supersedes_id}
    matching = [item for item in matching if item.id not in superseded_ids]
    recorded = [item for item in matching if item.evidence_status != "unknown"]
    values = {_normalized(_value(item)) for item in recorded if _value(item) is not None}
    contested = bool(
        any(item.evidence_status == "conflicted" for item in recorded)
        or len(values) > 1
    )
    if matching:
        observed_values = [_value(item) for item in recorded if _value(item) is not None]
        observed: Any = observed_values[0] if len(values) == 1 and observed_values else None
        statuses = {
            _freshness(
                item.observed_at,
                now=now,
                max_age_hours=_FRESHNESS_HOURS["specification"],
                expires_at=item.expires_at,
            )
            for item in matching
        }
        fresh = "stale" if "stale" in statuses else "fresh" if statuses == {"fresh"} else "unknown"
        classes = {str(item.claim_class) for item in recorded}
        claim_class = (
            "attested" if classes == {"attested"}
            else "behavioral" if classes == {"behavioural"}
            else "derived" if classes == {"derived"}
            else "catalog_observation"
        )
        verified = bool(
            recorded
            and not contested
            and all(item.evidence_status == "observed" for item in recorded)
            # Freshness is not derivation approval. A model/rule-derived value
            # remains visible but cannot establish independently verified fit.
            and not classes.intersection({"substitutable", "derived"})
            and fresh == "fresh"
        )
        return {
            "observed": observed,
            "contested": contested,
            "verified": verified,
            "claim_class": claim_class,
            "claim_ids": [item.id for item in matching],
            "freshness": fresh,
            "caveat": (
                "conflicting product observations are retained"
                if contested else
                "component is substitutable; exact installed part is not guaranteed"
                if "substitutable" in classes else
                "derived observation requires reviewed rule provenance"
                if "derived" in classes else None
            ),
        }
    field = _CAPABILITY_FIELDS.get(attribute)
    observed = getattr(row, field, None) if field else None
    fresh = _freshness(
        row.specification_observed_at,
        now=now,
        max_age_hours=_FRESHNESS_HOURS["specification"],
    )
    return {
        "observed": observed,
        "contested": False,
        "verified": bool(observed is not None and row.source_url and fresh == "fresh"),
        "claim_class": "catalog_observation",
        "claim_ids": (
            [f"configuration:{row.id}:{attribute}"] if observed is not None else []
        ),
        "freshness": fresh if observed is not None else "unknown",
        "caveat": None,
    }


def _identity(row: ProductConfiguration) -> ProductConfigurationIdentity:
    canonical_form = (
        "mobile_workstation" if row.device_class == "mobile_workstation"
        else "fixed_workstation" if row.device_class in {"desktop_workstation", "fixed_workstation"}
        else "server" if row.device_class == "server" or row.form_factor == "server"
        else "cloud" if row.device_class == "cloud" or row.form_factor == "cloud"
        else "laptop" if row.form_factor == "laptop"
        else "desktop" if row.form_factor in {"desktop", "desktop_tower", "sff_desktop"}
        else "unknown"
    )
    identifier_type = "mpn" if row.mpn else "retailer_sku" if row.retailer_sku else "unresolved"
    return ProductConfigurationIdentity(
        sku=row.sku, identifier_type=identifier_type,
        identifier=row.mpn or row.retailer_sku or "",
        configuration_hash=row.configuration_hash or configuration_hash(
            sku=row.sku, form_factor=canonical_form, specs={
                "mpn": row.mpn, "ram_gb": row.ram_installed_gb,
                "storage_gb": row.storage_gb, "gpu_vram_gb": row.gpu_vram_gb,
                "gpu_tgp_w": row.gpu_tgp_w, "os_edition": row.os_edition,
            },
        ),
        form_factor=canonical_form,
    )


def _identity_evidence(
    row: ProductConfiguration,
    observations: Sequence[ProductEvidenceObservation],
) -> ProductIdentityEvidenceProjection:
    identity_rows = [
        item for item in observations
        if item.attribute_key in {"manufacturer_part_number", "mpn"}
        and item.evidence_status != "unknown"
    ]
    observed_mpns = {
        _normalized(_value(item)) for item in identity_rows if _value(item) is not None
    }
    configured_mpn = _normalized(row.mpn)
    conflicting = bool(
        any(item.evidence_status == "conflicted" for item in identity_rows)
        or len(observed_mpns) > 1
        or (configured_mpn and observed_mpns and configured_mpn not in observed_mpns)
    )
    source_names = {_normalized(item.source_id) for item in identity_rows}
    manufacturer_source = _normalized(row.manufacturer)
    retailer_source = _normalized(row.retailer)
    reconciled = bool(
        configured_mpn
        and manufacturer_source in source_names
        and retailer_source in source_names
        and manufacturer_source != retailer_source
        and not conflicting
    )
    status = (
        "conflicted" if conflicting else
        "reconciled_oem_retailer" if reconciled else
        "retailer_attested" if configured_mpn and (row.source_url or identity_rows) else
        "unresolved"
    )
    return ProductIdentityEvidenceProjection(
        status=status,
        manufacturer=row.manufacturer,
        mpn=row.mpn,
        retailer_sku=row.retailer_sku,
        retailer=row.retailer,
        source_url=row.source_url,
        configuration_hash=row.configuration_hash,
        claim_ids=[item.id for item in identity_rows],
    )


def _decision(
    row: ProductConfiguration,
    claims: Sequence[Mapping[str, Any]],
    *,
    scope_id: str,
    desired_outcome: str,
    budget_cents: int | None,
    observations: Sequence[ProductEvidenceObservation],
    availability_status: str,
    now: datetime,
    contract=None,
):
    identity = _identity(row)
    ledger: list[FitLedgerRow] = []
    for claim in claims:
        attribute = str(claim.get("attribute") or "")
        # Source-neutral extraction uses ``conditional`` for publisher tiers
        # such as Basic/Advanced/Extreme.  The decision ledger represents the
        # same fact as a target requirement scoped by ``condition``; do not let
        # a reviewed generic source crash catalog projection merely because the
        # two bounded vocabularies use different names.
        raw_requirement_class = str(claim.get("requirement_class") or "minimum")
        requirement_class = (
            "target" if raw_requirement_class == "conditional"
            else raw_requirement_class
        )
        capability = _evidence_for_attribute(row, attribute, observations, now=now)
        observed = capability["observed"]
        verdict = "contested" if capability["contested"] else _verdict(claim, observed)
        requirement_verified = claim.get("authority_status") == "verified_official"
        ledger.append(FitLedgerRow(
            attribute_key=attribute,
            attribute_label=attribute.replace("_", " "),
            requirement_class=requirement_class,
            required=[[str(claim.get("operator") or "="), claim.get("value")]],
            required_text=f"{claim.get('operator')} {claim.get('value')}",
            observed=observed,
            observed_text="not recorded" if observed is None else str(observed),
            verdict=verdict,
            verification_status=(
                "verified" if requirement_verified and capability["verified"] else "unverified"
            ),
            claim_class=capability["claim_class"],
            requirement_claim_ids=[str(claim.get("claim_id"))],
            capability_claim_ids=capability["claim_ids"],
            scope_caveat=(
                str(claim.get("condition") or "") or capability["caveat"]
            ),
            freshness_status=capability["freshness"],
            resolver="catalog_evidence_ledger",
        ))
    from src.app.services.recommendation_core.requirement_scope import accepted_requirement_gaps
    completeness_gaps = accepted_requirement_gaps(claims, tenant_id=row.tenant_id,contract=contract,now=now)
    workload = WorkloadContract(
        desired_outcome=desired_outcome, artefact_name="buyer-accepted provisional scope",
        budget_cents=budget_cents, currency="AUD", surviving_hypothesis_ids=[scope_id],
        material_unknowns=completeness_gaps + (
            [] if claims and all(
                claim.get("authority_status") == "verified_official"
                for claim in claims
            ) else ["buyer-supplied requirements are not independently corroborated"]
        ),
    )
    return reduce_workload_decision(
        workload=workload, product=identity, rows=ledger,
        budget_status="over" if budget_cents is not None and row.price_cents > budget_cents else "within" if budget_cents is not None else "unknown",
        availability_status=availability_status,
    )


def _configuration_freshness(
    row: ProductConfiguration,
    availability: Sequence[ProductAvailabilityObservation],
    *,
    now: datetime,
) -> EvidenceFreshnessProjection:
    availability_times = [
        parsed for item in availability
        if (parsed := _as_utc(item.observed_at)) is not None
    ]
    latest_availability = max(availability_times) if availability_times else _as_utc(
        row.availability_observed_at,
    )
    return EvidenceFreshnessProjection(
        specification=_freshness(
            row.specification_observed_at, now=now,
            max_age_hours=_FRESHNESS_HOURS["specification"],
        ),
        specification_observed_at=(
            _as_utc(row.specification_observed_at).isoformat()
            if _as_utc(row.specification_observed_at) else None
        ),
        price=_freshness(
            row.price_observed_at, now=now, max_age_hours=_FRESHNESS_HOURS["price"],
        ),
        price_observed_at=(
            _as_utc(row.price_observed_at).isoformat()
            if _as_utc(row.price_observed_at) else None
        ),
        availability=_freshness(
            latest_availability, now=now,
            max_age_hours=_FRESHNESS_HOURS["availability"],
        ),
        availability_observed_at=(
            latest_availability.isoformat() if latest_availability else None
        ),
    )


def _availability_projection(
    observations: Sequence[ProductAvailabilityObservation], *, now: datetime,
) -> tuple[list[AvailabilityProjection], str]:
    rows: list[AvailabilityProjection] = []
    for item in observations:
        rows.append(AvailabilityProjection(
            location_id=item.location_id,
            status=item.status,
            quantity=item.quantity,
            lead_time_min_days=item.lead_time_min_days,
            lead_time_max_days=item.lead_time_max_days,
            observed_at=_as_utc(item.observed_at).isoformat() if _as_utc(item.observed_at) else None,
            freshness_status=_freshness(
                item.observed_at, now=now,
                max_age_hours=_FRESHNESS_HOURS["availability"],
                expires_at=item.expires_at,
            ),
        ))
    fresh_rows = [item for item in rows if item.freshness_status == "fresh"]
    if any(item.status in {"in_stock", "available"} and item.quantity != 0 for item in fresh_rows):
        status = "available"
    elif fresh_rows and all(item.status == "sold_out" or item.quantity == 0 for item in fresh_rows):
        status = "unavailable"
    else:
        status = "unknown"
    return rows, status


def _weighted_relevance(decision: Any) -> float:
    weights = {"minimum": 4.0, "target": 3.0, "recommended": 2.0, "optimal": 1.0}
    total = sum(weights.get(item.requirement_class, 1.0) for item in decision.fit_ledger)
    if not total:
        return 0.0
    earned = sum(
        weights.get(item.requirement_class, 1.0)
        for item in decision.fit_ledger
        if item.verdict in {"meets_minimum", "meets_recommended"}
    )
    return earned / total


def _candidate_relevance(decisions: Mapping[str, Any]) -> float:
    score = max((_weighted_relevance(item) for item in decisions.values()), default=0.0)
    if score > 0:
        return score
    # A contested or below-minimum exact attribute is still relevant evidence;
    # zero relevance means the catalog has no observed attribute for the
    # accepted requirement, not merely that the product failed it.
    return 0.01 if any(
        row.observed is not None or bool(row.capability_claim_ids)
        for decision in decisions.values()
        for row in decision.fit_ledger
    ) else 0.0


def project_accepted_catalog(
    db,
    *,
    accepted_claims: Sequence[Mapping[str, Any]],
    desired_outcome: str = "Buyer accepted requirements",
    budget_cents: int | None = None,
    stretch_budget_cents: int | None = None,
    requested_quantity: int | None = None,
    tenant_id: str = "default",
    hypothesis_labels: Mapping[str, str] | None = None,
    hypothesis_claims: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    candidate_configuration_ids: Sequence[str] | None = None,
    now: datetime | None = None,
    case_id: str | None = None,
    uid: str | None = None,
    availability_observations: Sequence[ProductAvailabilityObservation] | None = None,
) -> ProductShelfProjection:
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    contract_receipt = None
    selected_contract = None
    if case_id is not None:
        from src.app.services.case_contract_binding import gate_case_contract_consumption
        accepted_claims, contract_receipt = gate_case_contract_consumption(
            db,tenant_id=tenant_id,case_id=case_id,uid=uid,claims=accepted_claims,now=observed_now)
        if contract_receipt['state']=='current':
            from src.app.services.case_contract_binding import require_current_case_contract
            selected_contract,_=require_current_case_contract(db,tenant_id=tenant_id,case_id=case_id,
                uid=uid,binding_id=contract_receipt['binding_id'])
        if contract_receipt['state'] != 'unselected':
            allowed_ids = {id(claim) for claim in accepted_claims}
            hypothesis_claims = {key:[claim for claim in claims if id(claim) in allowed_ids]
                                 for key,claims in (hypothesis_claims or {}).items()}
    candidate_query = select(ProductConfiguration).where(
        ProductConfiguration.tenant_id == tenant_id,
        ProductConfiguration.active.is_(True),
    )
    # Missing scope is not authority to enumerate the tenant catalog. Every
    # caller, including administrative previews, must supply its candidate set.
    bounded_ids = [str(value) for value in (candidate_configuration_ids or ()) if str(value)]
    rows = db.execute(candidate_query.where(
        ProductConfiguration.id.in_(bounded_ids),
    )).scalars().all() if bounded_ids else []
    configuration_ids = [row.id for row in rows]
    evidence_by_configuration: dict[str, list[ProductEvidenceObservation]] = defaultdict(list)
    availability_by_configuration: dict[str, list[ProductAvailabilityObservation]] = defaultdict(list)
    if configuration_ids:
        for item in db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.configuration_id.in_(configuration_ids),
        )).scalars():
            evidence_by_configuration[item.configuration_id].append(item)
        # Trusted server adapters may supply current stock observations. Never
        # accept this override from buyer/model payloads or mix it with old snapshots.
        observations = availability_observations if availability_observations is not None else db.execute(
            select(ProductAvailabilityObservation).where(
                ProductAvailabilityObservation.configuration_id.in_(configuration_ids))).scalars()
        for item in observations:
            if item.configuration_id in configuration_ids:
                availability_by_configuration[item.configuration_id].append(item)
    conditional = [claim for claim in accepted_claims if claim.get("condition")]
    shared_claims = [claim for claim in accepted_claims if not claim.get("condition")]
    proposed_labels = {
        str(key).strip(): str(value).strip()
        for key, value in dict(hypothesis_labels or {}).items()
        if str(key).strip() and str(value).strip()
    }
    scoped_claims = {
        str(scope_id): list(rows)
        for scope_id, rows in dict(hypothesis_claims or {}).items()
        if str(scope_id).strip()
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
        observations = evidence_by_configuration[row.id]
        availability, availability_status = _availability_projection(
            availability_by_configuration[row.id], now=observed_now,
        )
        decisions = {
            "shared": _decision(
                row, shared_claims, scope_id="shared", desired_outcome=desired_outcome,
                budget_cents=budget_cents,
                observations=observations, availability_status=availability_status,
                now=observed_now,contract=selected_contract,
            ),
        }
        if conditional:
            decisions["conditional_scope"] = _decision(
                row, [*shared_claims, *conditional], scope_id="conditional_scope",
                desired_outcome=desired_outcome, budget_cents=budget_cents,
                observations=observations, availability_status=availability_status,
                now=observed_now,contract=selected_contract,
            )
        architecture_scope = f"architecture:{row.device_class}"
        decisions[architecture_scope] = _decision(
            row, shared_claims, scope_id=architecture_scope,
            desired_outcome=desired_outcome, budget_cents=budget_cents,
            observations=observations, availability_status=availability_status,
            now=observed_now,contract=selected_contract,
        )
        for hypothesis_id in proposed_labels:
            claims_for_hypothesis = list({
                str(claim.get("claim_id") or index): claim
                for index, claim in enumerate([
                    *shared_claims, *scoped_claims.get(hypothesis_id, []),
                ])
            }.values())
            decisions[hypothesis_id] = _decision(
                row, claims_for_hypothesis, scope_id=hypothesis_id,
                desired_outcome=desired_outcome, budget_cents=budget_cents,
                observations=observations, availability_status=availability_status,
                now=observed_now,contract=selected_contract,
            )
        candidates.append(ShelfCandidateInput(
            product=identity, title=row.title, price_cents=row.price_cents,
            relevance_score=_candidate_relevance(decisions),
            fit_by_scope=decisions,
            evidence_freshness=_configuration_freshness(
                row, availability_by_configuration[row.id], now=observed_now,
            ),
            availability=availability,
            identity_evidence=_identity_evidence(row, observations),
        ))
    projection = build_product_shelves(
        candidates, hypothesis_ids=hypothesis_ids, scope_labels=labels,
        budget_cents=budget_cents, requested_quantity=requested_quantity,
        stretch_budget_cents=stretch_budget_cents,
        suppress_zero_relevance=bool(accepted_claims), suppress_unavailable=True,
    )
    return projection.model_copy(update={'requirement_contract':contract_receipt})


__all__ = ["project_accepted_catalog"]
