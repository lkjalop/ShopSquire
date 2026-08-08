"""Reviewed seed configurations used by the workload-fit acceptance journey.

These records are deliberately small and explicit.  Values absent from the reviewed
source stay ``None``; no attribute is copied between similar GPU or product names.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.app.models.orm import (
    Product,
    ProductAvailabilityObservation,
    ProductConfiguration,
    ProductEvidenceObservation,
)


ClaimClass = Literal["attested", "derived", "behavioural", "substitutable"]


class SeedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribute_key: str
    value: Any
    unit: str | None = None
    claim_class: ClaimClass
    status: Literal["observed", "conflicted", "unknown"] = "observed"
    conflict_group: str | None = None
    excerpt: str | None = None


class SeedAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_id: str
    status: Literal["in_stock", "at_supplier", "sold_out", "built_to_order", "available"]
    quantity: int | None = None
    lead_time_min_days: int | None = None
    lead_time_max_days: int | None = None


class ReviewedConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str
    title: str
    manufacturer: str
    mpn: str
    retailer_sku: str | None = None
    retailer: str
    source_url: str
    price_cents: int
    form_factor: str
    mobility: str
    device_class: str
    os_edition: str
    gpu_class: str
    gpu_vram_gb: int | None = None
    gpu_tgp_w: int | None = None
    ram_installed_gb: int
    ram_ceiling_gb: int | None = None
    ram_upgradeable: bool | None = None
    storage_gb: int
    warranty_type: str | None = None
    warranty_years: int | None = None
    claims: list[SeedClaim] = Field(default_factory=list)
    availability: list[SeedAvailability] = Field(default_factory=list)


SOURCE_DATE = datetime(2026, 8, 8, tzinfo=timezone.utc)


REVIEWED_CONFIGURATIONS: tuple[ReviewedConfiguration, ...] = (
    ReviewedConfiguration(
        sku="SCORP-126982", title="MSI Titan 18 HX A2WJ RTX 5090 Laptop",
        manufacturer="MSI", mpn="Titan 18 HX A2WJ-1038AU", retailer_sku="126982",
        retailer="Scorptec", source_url="https://www.scorptec.com.au/product/laptops-and-notebooks/gaming-laptops/126982-titan-18-hx-a2wj-1038au",
        price_cents=899_900, form_factor="laptop", mobility="mobile_limited",
        device_class="consumer_gaming_flagship", os_edition="Windows 11 Pro",
        gpu_class="consumer_geforce", gpu_vram_gb=24, gpu_tgp_w=175,
        ram_installed_gb=64, ram_ceiling_gb=128, ram_upgradeable=True,
        storage_gb=2000, warranty_type="unspecified", warranty_years=2,
        claims=[
            SeedClaim(attribute_key="gpu_vram_gb", value=24, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="gpu_tgp_w", value=175, unit="W", claim_class="attested"),
            SeedClaim(attribute_key="fleet_manageable", value=True, claim_class="derived"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="in_stock"), SeedAvailability(location_id="dandenong", status="in_stock")],
    ),
    ReviewedConfiguration(
        sku="SCORP-125638", title="ASUS ROG Zephyrus Duo GX651 RTX 5090 Laptop",
        manufacturer="ASUS", mpn="GX651AX-SR004W", retailer_sku="125638",
        retailer="Scorptec", source_url="https://www.scorptec.com.au/product/laptops-and-notebooks/gaming-laptops/125638-gx651ax-sr004w",
        price_cents=1_299_900, form_factor="laptop", mobility="mobile",
        device_class="consumer_gaming_flagship", os_edition="Windows 11 Pro",
        gpu_class="consumer_geforce", gpu_vram_gb=24, gpu_tgp_w=None,
        ram_installed_gb=64, ram_ceiling_gb=None, ram_upgradeable=False,
        storage_gb=2000, warranty_type="unspecified", warranty_years=1,
        claims=[
            SeedClaim(attribute_key="gpu_vram_gb", value=24, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="gpu_tgp_w", value=None, unit="W", claim_class="attested", status="unknown"),
            SeedClaim(attribute_key="ram_upgradeable", value=False, claim_class="derived", excerpt="LPDDR5X soldered"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="in_stock"), SeedAvailability(location_id="tingalpa", status="sold_out")],
    ),
    ReviewedConfiguration(
        sku="JW-822962", title="HP ZBook Fury G1i 16 Mobile Workstation",
        manufacturer="HP", mpn="C2EN9PT-CTO-128G5T", retailer_sku="822962",
        retailer="JW Computers", source_url="https://www.jw.com.au/product/hp-zbook-f-16-touchscreen-mobile-workstation-ultra-9-285hx-128gb-ram-5tb-1tb-4tb-ssd-rtx-pro-4000-windows-11-pro",
        price_cents=1_499_900, form_factor="laptop", mobility="mobile",
        device_class="mobile_workstation", os_edition="Windows 11 Pro",
        gpu_class="professional_rtx_pro", gpu_vram_gb=None, gpu_tgp_w=None,
        ram_installed_gb=128, ram_ceiling_gb=None, ram_upgradeable=None,
        storage_gb=5000, warranty_type="onsite", warranty_years=3,
        claims=[
            SeedClaim(attribute_key="device_class", value="mobile_workstation", claim_class="derived"),
            SeedClaim(attribute_key="isv_certifiable", value="likely", claim_class="derived", status="unknown"),
            SeedClaim(attribute_key="ecc_memory", value=None, claim_class="attested", status="unknown"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="available", lead_time_min_days=2, lead_time_max_days=4)],
    ),
    ReviewedConfiguration(
        sku="SCORP-C07NXPT", title="HP Z2 Mini G1a Workstation",
        manufacturer="HP", mpn="C07NXPT", retailer="Scorptec",
        source_url="https://www.scorptec.com.au/product/branded-systems/workstation/123163-c07nxpt",
        price_cents=369_900, form_factor="sff_desktop", mobility="fixed",
        device_class="desktop_workstation", os_edition="Windows 11 Pro",
        gpu_class="integrated", gpu_vram_gb=None, gpu_tgp_w=None,
        ram_installed_gb=32, ram_ceiling_gb=None, ram_upgradeable=False,
        storage_gb=1000, warranty_type="onsite_nbd", warranty_years=3,
        claims=[
            SeedClaim(attribute_key="device_class", value="desktop_workstation", claim_class="derived"),
            SeedClaim(attribute_key="gpu_vram_gb", value=None, unit="GB", claim_class="attested", status="unknown"),
            SeedClaim(attribute_key="ram_upgradeable", value=False, claim_class="derived", excerpt="LPDDR5X soldered"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="at_supplier")],
    ),
    ReviewedConfiguration(
        sku="JW-818845", title="GMR Zephyr 5090 Gaming PC",
        manufacturer="GMR", mpn="GMR-ZEPHYR-01-5090", retailer_sku="818845",
        retailer="JW Computers", source_url="https://www.jw.com.au/product/gmr-zephyr-5090-gaming-pc",
        price_cents=899_900, form_factor="desktop_tower", mobility="fixed",
        device_class="consumer_gaming_flagship", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=32, gpu_tgp_w=None,
        ram_installed_gb=32, ram_ceiling_gb=None, ram_upgradeable=True,
        storage_gb=2000, warranty_type="rtb", warranty_years=2,
        claims=[
            SeedClaim(attribute_key="cpu_model", value="Ryzen 7 9800X3D", claim_class="attested", status="conflicted", conflict_group="zephyr-cpu"),
            SeedClaim(attribute_key="cpu_model", value="Ryzen 7 7800X3D", claim_class="attested", status="conflicted", conflict_group="zephyr-cpu"),
            SeedClaim(attribute_key="gpu_vram_gb", value=32, unit="GB", claim_class="substitutable", excerpt="PNY XLR8 RTX 5090 32G or equivalent"),
            SeedClaim(attribute_key="storage_gb", value=2000, unit="GB", claim_class="substitutable"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="built_to_order", lead_time_min_days=6, lead_time_max_days=8)],
    ),
)


def configuration_hash(item: ReviewedConfiguration) -> str:
    material = item.model_dump(exclude={"claims", "availability"})
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def ingest_reviewed_configurations(db, *, tenant_id: str = "default") -> list[str]:
    """Idempotently ingest the reviewed five-record fixture."""
    ids: list[str] = []
    for item in REVIEWED_CONFIGURATIONS:
        digest = configuration_hash(item)
        product = db.execute(select(Product).where(Product.sku == item.sku)).scalar_one_or_none()
        if product is None:
            product = Product(
                sku=item.sku, name=item.title, price_cents=item.price_cents,
                currency="AUD", active=True, image_url=None,
                specs={
                    "manufacturer": item.manufacturer, "mpn": item.mpn,
                    "retailer_sku": item.retailer_sku, "form_factor": item.form_factor,
                    "device_class": item.device_class, "os_edition": item.os_edition,
                    "gpu_class": item.gpu_class, "gpu_vram_gb": item.gpu_vram_gb,
                    "ram_gb": item.ram_installed_gb, "storage_gb": item.storage_gb,
                    "source_url": item.source_url,
                    "availability_authority": "product_availability_observations",
                },
            )
            db.add(product)
            db.flush()
        existing = db.execute(select(ProductConfiguration).where(
            ProductConfiguration.tenant_id == tenant_id,
            ProductConfiguration.sku == item.sku,
            ProductConfiguration.configuration_hash == digest,
        )).scalar_one_or_none()
        if existing is not None:
            if existing.product_id != product.id:
                existing.product_id = product.id
            ids.append(existing.id)
            continue
        config = ProductConfiguration(
            tenant_id=tenant_id, product_id=product.id, configuration_hash=digest,
            specification_observed_at=SOURCE_DATE, price_observed_at=SOURCE_DATE,
            availability_observed_at=SOURCE_DATE, currency="AUD", active=True,
            **item.model_dump(exclude={"claims", "availability"}),
        )
        db.add(config)
        db.flush()
        for index, claim in enumerate(item.claims):
            db.add(ProductEvidenceObservation(
                configuration_id=config.id, attribute_key=claim.attribute_key,
                value_json={"value": claim.value}, unit=claim.unit,
                claim_class=claim.claim_class, evidence_status=claim.status,
                conflict_group=claim.conflict_group, source_id=item.retailer,
                source_record_id=f"{item.source_url}#{index}", source_excerpt=claim.excerpt,
                observed_at=SOURCE_DATE,
            ))
        for index, row in enumerate(item.availability):
            db.add(ProductAvailabilityObservation(
                configuration_id=config.id, source_record_id=f"{item.source_url}#availability-{index}",
                observed_at=SOURCE_DATE, **row.model_dump(),
            ))
        ids.append(config.id)
    db.commit()
    return ids


__all__ = ["REVIEWED_CONFIGURATIONS", "configuration_hash", "ingest_reviewed_configurations"]
