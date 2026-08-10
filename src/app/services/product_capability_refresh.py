"""Persist governed exact-configuration capability observations.

Specification refresh is deliberately independent from price and availability.
Conflicting observations are appended, never overwritten or force-resolved.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select

from src.app.models.orm import ProductConfiguration, ProductEvidenceObservation
from src.app.services.connectors.product_capability_evidence import (
    ProductCapabilityEvidenceRegistry,
    ProductIdentity,
)


DEFAULT_CAPABILITY_KEYS = (
    "operating_system", "cpu_model", "gpu_class", "gpu_vram_gb", "gpu_tgp_w",
    "ram_gb", "ram_ceiling_gb", "ram_upgradeable", "storage_gb", "warranty_type",
    "warranty_years",
)


def refresh_exact_configuration_capabilities(
    db: Any,
    configuration: ProductConfiguration,
    *,
    registry: ProductCapabilityEvidenceRegistry,
    claim_keys: Iterable[str] = DEFAULT_CAPABILITY_KEYS,
    allow_live: bool = True,
) -> dict[str, Any]:
    identity = ProductIdentity(
        sku=configuration.sku,
        identifier_type="manufacturer_part_number",
        identifier=str(configuration.mpn or ""),
        configuration_hash=configuration.configuration_hash,
        form_factor="laptop" if configuration.form_factor == "laptop" else configuration.form_factor,
    )
    result = registry.resolve(
        identity,
        claim_keys=tuple(claim_keys),
        allow_live=allow_live,
        tenant_id=configuration.tenant_id,
    )
    inserted = 0
    observed_values: list[dict[str, Any]] = []
    newest_observed_at: datetime | None = None
    for claim in result.accepted_claims:
        source_record_id = str(claim.get("source_record_id") or "").strip()
        attribute_key = str(claim.get("attribute_key") or "").strip()
        if not source_record_id or not attribute_key:
            continue
        observed_at = datetime.fromisoformat(str(claim["retrieved_at"]).replace("Z", "+00:00"))
        existing = db.execute(select(ProductEvidenceObservation.id).where(
            ProductEvidenceObservation.configuration_id == configuration.id,
            ProductEvidenceObservation.source_record_id == source_record_id,
            ProductEvidenceObservation.attribute_key == attribute_key,
        )).scalar_one_or_none()
        if existing is None:
            db.add(ProductEvidenceObservation(
                configuration_id=configuration.id,
                attribute_key=attribute_key,
                value_json={"value": claim.get("value")},
                unit=claim.get("unit"),
                claim_class=str(claim.get("claim_class") or "attested"),
                evidence_status="observed",
                source_id=str(claim.get("provider_id") or "official_product_source"),
                source_record_id=source_record_id,
                source_excerpt=str(claim.get("scope_caveat") or "")[:500] or None,
                observed_at=observed_at,
            ))
            inserted += 1
        observed_values.append({
            "attribute_key": attribute_key,
            "value": claim.get("value"),
            "unit": claim.get("unit"),
            "source_url": claim.get("source_url"),
            "source_record_id": source_record_id,
        })
        if newest_observed_at is None or observed_at > newest_observed_at:
            newest_observed_at = observed_at
    if newest_observed_at is not None:
        configuration.specification_observed_at = newest_observed_at
    db.commit()
    return {
        "status": result.status,
        "sku": configuration.sku,
        "mpn": configuration.mpn,
        "claims_observed": len(observed_values),
        "observations_inserted": inserted,
        "conflicts_reported_by_current_refresh": list(result.conflicts),
        "unknown_claim_keys": list(result.unknown_claim_keys),
        "attempts": list(result.attempts),
        "specification_observed_at": (
            newest_observed_at.isoformat() if newest_observed_at is not None else None
        ),
        "price_observed_at": (
            configuration.price_observed_at.isoformat()
            if hasattr(configuration.price_observed_at, "isoformat") else configuration.price_observed_at
        ),
        "availability_observed_at": (
            configuration.availability_observed_at.isoformat()
            if hasattr(configuration.availability_observed_at, "isoformat") else configuration.availability_observed_at
        ),
        "observed_values": observed_values,
    }


__all__ = ["DEFAULT_CAPABILITY_KEYS", "refresh_exact_configuration_capabilities"]
