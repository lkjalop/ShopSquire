"""Reviewed seed configurations used by the workload-fit acceptance journey.

These records are deliberately small and explicit.  Values absent from the reviewed
source stay ``None``; no attribute is copied between similar GPU or product names.
"""
from __future__ import annotations

import hashlib
import json
import os
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
    official_source_url: str | None = None
    official_identity_scope: Literal["exact_configuration", "family_only", "unavailable"] = "unavailable"
    official_reviewed_at: datetime | None = None
    reviewed_at: datetime = Field(
        default_factory=lambda: datetime(2026, 8, 8, tzinfo=timezone.utc),
    )
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
    official_claims: list[SeedClaim] = Field(default_factory=list)
    availability: list[SeedAvailability] = Field(default_factory=list)


SOURCE_DATE = datetime(2026, 8, 8, tzinfo=timezone.utc)
OEM_REVIEW_DATE = datetime(2026, 8, 11, tzinfo=timezone.utc)
PORTABLE_REVIEW_DATE = datetime(2026, 8, 12, tzinfo=timezone.utc)


REVIEWED_CONFIGURATIONS: tuple[ReviewedConfiguration, ...] = (
    ReviewedConfiguration(
        sku="SCORP-126982", title="MSI Titan 18 HX A2WJ RTX 5090 Laptop",
        manufacturer="MSI", mpn="Titan 18 HX A2WJ-1038AU", retailer_sku="126982",
        retailer="Scorptec", source_url="https://www.scorptec.com.au/product/laptops-and-notebooks/gaming-laptops/126982-titan-18-hx-a2wj-1038au",
        official_source_url="https://au.msi.com/Laptop/Titan-18-HX-A2WX/Specification",
        official_identity_scope="exact_configuration",
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
        official_claims=[
            SeedClaim(attribute_key="operating_system", value="Windows 11 Pro", claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=24, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="gpu_tgp_w", value=175, unit="W", claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="in_stock"), SeedAvailability(location_id="dandenong", status="in_stock")],
    ),
    ReviewedConfiguration(
        sku="SCORP-125638", title="ASUS ROG Zephyrus Duo GX651 RTX 5090 Laptop",
        manufacturer="ASUS", mpn="GX651AX-SR004W", retailer_sku="125638",
        retailer="Scorptec", source_url="https://www.scorptec.com.au/product/laptops-and-notebooks/gaming-laptops/125638-gx651ax-sr004w",
        official_source_url="https://rog.asus.com/au/laptops/rog-zephyrus/rog-zephyrus-duo-2026/spec/",
        official_identity_scope="exact_configuration",
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
        official_claims=[
            SeedClaim(attribute_key="operating_system", value="Windows 11 Home", claim_class="attested", status="conflicted", conflict_group="gx651ax-os"),
            SeedClaim(attribute_key="gpu_vram_gb", value=24, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ram_gb", value=64, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="storage_gb", value=2000, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ram_upgradeable", value=False, claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="in_stock"), SeedAvailability(location_id="tingalpa", status="sold_out")],
    ),
    ReviewedConfiguration(
        sku="JW-822962", title="HP ZBook Fury G1i 16 Mobile Workstation",
        manufacturer="HP", mpn="C2EN9PT-CTO-128G5T", retailer_sku="822962",
        retailer="JW Computers", source_url="https://www.jw.com.au/product/hp-zbook-f-16-touchscreen-mobile-workstation-ultra-9-285hx-128gb-ram-5tb-1tb-4tb-ssd-rtx-pro-4000-windows-11-pro",
        official_source_url="https://support.hp.com/us-en/document/ish_12456093-12456254-16",
        official_identity_scope="family_only",
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
        sku="UMART-85002",
        title="MSI CreatorPro X18 HX A14VMG RTX 5000 Ada Mobile Workstation",
        manufacturer="MSI", mpn="CreatorPro X18 HX A14VMG-453AU",
        retailer_sku="85002", retailer="Umart",
        source_url=(
            "https://www.umart.com.au/product/msi-creatorpro-x18-hx-a14vmg-18in-"
            "uhd-120hz-core-i9-14900hx-rtx-5000-2tb-ssd-64gb-ram-w11p-laptop-"
            "creatorpro-x18-hx-a14vmg-453au-85002"
        ),
        official_source_url=(
            "https://storage-asset.msi.com/specSheet/au/content-creation/"
            "CreatorPro%20X18%20HX%20A14VMG-453AU.pdf"
        ),
        official_identity_scope="exact_configuration",
        reviewed_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        official_reviewed_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        price_cents=899_900, form_factor="laptop", mobility="mobile_limited",
        device_class="mobile_workstation", os_edition="Windows 11 Pro",
        gpu_class="professional_rtx_5000_ada", gpu_vram_gb=16, gpu_tgp_w=175,
        ram_installed_gb=64, ram_ceiling_gb=192, ram_upgradeable=True,
        storage_gb=4000, warranty_type="manufacturer", warranty_years=3,
        claims=[
            SeedClaim(attribute_key="cpu_model", value="Intel Core i9-14900HX", claim_class="attested"),
            SeedClaim(attribute_key="cpu_physical_cores", value=24, claim_class="attested"),
            SeedClaim(attribute_key="cpu_boost_ghz", value=5.8, unit="GHz", claim_class="attested"),
            SeedClaim(attribute_key="gpu_family", value="NVIDIA RTX 5000 Ada", claim_class="attested"),
            SeedClaim(attribute_key="ethernet_adapter", value="Intel Killer E3100 2.5Gbps", claim_class="attested"),
            SeedClaim(attribute_key="isv_certified", value=True, claim_class="attested"),
        ],
        official_claims=[
            SeedClaim(attribute_key="operating_system", value="Windows 11 Pro", claim_class="attested"),
            SeedClaim(attribute_key="cpu_model", value="Intel Core i9-14900HX", claim_class="attested"),
            SeedClaim(attribute_key="cpu_physical_cores", value=24, claim_class="attested"),
            SeedClaim(attribute_key="cpu_boost_ghz", value=5.8, unit="GHz", claim_class="attested"),
            SeedClaim(attribute_key="gpu_family", value="NVIDIA RTX 5000 Ada", claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=16, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="gpu_tgp_w", value=175, unit="W", claim_class="attested"),
            SeedClaim(attribute_key="ram_gb", value=64, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ram_ceiling_gb", value=192, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="storage_gb", value=4000, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ethernet_adapter", value="Intel Killer E3100 2.5Gbps", claim_class="attested"),
            SeedClaim(attribute_key="isv_certified", value=True, claim_class="attested"),
        ],
        availability=[SeedAvailability(
            location_id="australia_delivery", status="sold_out", quantity=0,
        )],
    ),
    ReviewedConfiguration(
        sku="JB-899169", title="Lenovo LOQ 15.6-inch RTX 3050 Gaming Laptop",
        manufacturer="Lenovo", mpn="83S000FKAU", retailer_sku="899169",
        retailer="JB Hi-Fi", source_url="https://www.jbhifi.com.au/products/lenovo-loq-15-6-full-hd-144hz-gaming-laptop-amd-ryzen-7-170geforce-rtx-3050",
        reviewed_at=PORTABLE_REVIEW_DATE,
        price_cents=169_900, form_factor="laptop", mobility="mobile",
        device_class="gaming_laptop", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=6, gpu_tgp_w=65,
        ram_installed_gb=16, storage_gb=512, warranty_type="manufacturer",
        warranty_years=1,
        claims=[
            SeedClaim(attribute_key="cpu_cores", value=8, claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=6, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="gpu_tgp_w", value=65, unit="W", claim_class="attested"),
            SeedClaim(attribute_key="ethernet_port", value=True, claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="available")],
    ),
    ReviewedConfiguration(
        sku="JB-816759", title="Lenovo Legion 5i 15.1-inch RTX 5070 Gaming Laptop",
        manufacturer="Lenovo", mpn="83LY001SAU", retailer_sku="816759",
        retailer="JB Hi-Fi", source_url="https://www.jbhifi.com.au/products/lenovo-legion-5i-15-1-wqxga-165hz-oled-gaming-laptop-intel-core-i9geforce-rtx-5070",
        reviewed_at=PORTABLE_REVIEW_DATE,
        price_cents=389_900, form_factor="laptop", mobility="mobile",
        device_class="gaming_laptop", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=8,
        ram_installed_gb=32, storage_gb=1000, warranty_type="manufacturer",
        warranty_years=1,
        claims=[
            SeedClaim(attribute_key="cpu_cores", value=24, claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=8, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ethernet_port", value=True, claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="available")],
    ),
    ReviewedConfiguration(
        sku="JB-840466", title="Lenovo Legion 9i 18-inch RTX 5080 Gaming Laptop",
        manufacturer="Lenovo", mpn="83EY004HAU", retailer_sku="840466",
        retailer="JB Hi-Fi", source_url="https://www.jbhifi.com.au/products/lenovo-legion-9i-18-wquxga-240hz-gaming-laptop-intel-core-ultra-9geforce-rtx-5080",
        reviewed_at=PORTABLE_REVIEW_DATE,
        price_cents=879_900, form_factor="laptop", mobility="mobile_limited",
        device_class="consumer_gaming_flagship", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=16,
        ram_installed_gb=64, storage_gb=2000, warranty_type="manufacturer",
        warranty_years=1,
        claims=[
            SeedClaim(attribute_key="cpu_cores", value=24, claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=16, unit="GB", claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="sold_out", quantity=0)],
    ),
    ReviewedConfiguration(
        sku="JB-896579", title="MSI Crosshair 16 HX RTX 5070 Gaming Laptop",
        manufacturer="MSI", mpn="6808864", retailer_sku="896579",
        retailer="JB Hi-Fi", source_url="https://www.jbhifi.com.au/products/msi-crosshair-16-hx-16-wqxga-240hz-gaming-laptop-intel-core-i9-14900hxnvidia-geforce-rtx-5070",
        reviewed_at=PORTABLE_REVIEW_DATE,
        price_cents=459_900, form_factor="laptop", mobility="mobile_limited",
        device_class="gaming_laptop", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=8,
        ram_installed_gb=32, storage_gb=1000, warranty_type="manufacturer",
        warranty_years=1,
        claims=[
            SeedClaim(attribute_key="cpu_cores", value=24, claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=8, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ethernet_port", value=True, claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="available")],
    ),
    ReviewedConfiguration(
        sku="JB-782503", title="MSI Thin A15 RTX 3050 Gaming Laptop",
        manufacturer="MSI", mpn="6267871", retailer_sku="782503",
        retailer="JB Hi-Fi", source_url="https://www.jbhifi.com.au/products/msi-thin-a15-15-fhd-144hz-gaming-laptop-ryzen-7-geforce-rtx-3050",
        reviewed_at=PORTABLE_REVIEW_DATE,
        price_cents=149_800, form_factor="laptop", mobility="mobile",
        device_class="gaming_laptop", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=4,
        ram_installed_gb=8, storage_gb=512, warranty_type="manufacturer",
        warranty_years=1,
        claims=[
            SeedClaim(attribute_key="cpu_cores", value=8, claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=4, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ethernet_port", value=True, claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="sold_out", quantity=0)],
    ),
    ReviewedConfiguration(
        sku="JB-840569", title="HP OMEN 15.3-inch RTX 5070 Gaming Laptop",
        manufacturer="HP", mpn="DB1M5PA#ABG", retailer_sku="840569",
        retailer="JB Hi-Fi", source_url="https://www.jbhifi.com.au/products/hyperx-omen-15-3-wqxga-gaming-laptop-intel-core-i7geforce-rtx-5070",
        reviewed_at=PORTABLE_REVIEW_DATE,
        price_cents=479_900, form_factor="laptop", mobility="mobile_limited",
        device_class="gaming_laptop", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=8,
        ram_installed_gb=24, storage_gb=1000, warranty_type="manufacturer",
        warranty_years=1,
        claims=[
            SeedClaim(attribute_key="cpu_cores", value=16, claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=8, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ethernet_port", value=True, claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="available")],
    ),
    ReviewedConfiguration(
        sku="SCORP-126560", title="Gigabyte AORUS MASTER 16 Gen 2 RTX 5090 Laptop",
        manufacturer="Gigabyte", mpn="AORUS MASTER 16 6ZJM6AUE64SH",
        retailer_sku="126560", retailer="Scorptec",
        source_url="https://www.scorptec.com.au/product/laptops-and-notebooks/gaming-laptops/126560-aorus-master-16-6zjm6aue64sh",
        reviewed_at=PORTABLE_REVIEW_DATE,
        price_cents=899_900, form_factor="laptop", mobility="mobile_limited",
        device_class="consumer_gaming_flagship", os_edition="Windows 11 Home",
        gpu_class="consumer_geforce", gpu_vram_gb=24,
        ram_installed_gb=32, storage_gb=1000, warranty_type="manufacturer",
        warranty_years=1,
        claims=[
            SeedClaim(attribute_key="cpu_cores", value=16, claim_class="attested"),
            SeedClaim(attribute_key="gpu_vram_gb", value=24, unit="GB", claim_class="attested"),
        ],
        availability=[SeedAvailability(location_id="australia_delivery", status="in_stock")],
    ),
    ReviewedConfiguration(
        sku="SCORP-C07NXPT", title="HP Z2 Mini G1a Workstation",
        manufacturer="HP", mpn="C07NXPT", retailer="Scorptec",
        source_url="https://www.scorptec.com.au/product/branded-systems/workstation/123163-c07nxpt",
        official_source_url="https://www.hp.com/nz-en/products/workstations/product-details/product-specifications/2103171150",
        official_identity_scope="exact_configuration",
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
        official_claims=[
            SeedClaim(attribute_key="operating_system", value="Windows 11 Pro", claim_class="attested"),
            SeedClaim(attribute_key="gpu_class", value="integrated", claim_class="attested"),
            SeedClaim(attribute_key="ram_gb", value=32, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="storage_gb", value=1000, unit="GB", claim_class="attested"),
            SeedClaim(attribute_key="ram_upgradeable", value=False, claim_class="attested"),
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


PORTFOLIO_DEMO_AVAILABILITY: dict[str, tuple[SeedAvailability, ...]] = {
    "SCORP-126982": (
        SeedAvailability(location_id="portfolio_network", status="in_stock", quantity=3),
    ),
    "SCORP-125638": (
        SeedAvailability(location_id="portfolio_network", status="sold_out", quantity=0),
    ),
    "JW-822962": (
        SeedAvailability(location_id="portfolio_network", status="available", quantity=2),
    ),
    "UMART-85002": (
        SeedAvailability(location_id="portfolio_network", status="sold_out", quantity=0),
    ),
    "JB-899169": (
        SeedAvailability(location_id="portfolio_network", status="in_stock", quantity=12),
    ),
    "JB-816759": (
        SeedAvailability(location_id="portfolio_network", status="in_stock", quantity=7),
    ),
    "JB-840466": (
        SeedAvailability(location_id="portfolio_network", status="sold_out", quantity=0),
    ),
    "JB-896579": (
        SeedAvailability(location_id="portfolio_network", status="in_stock", quantity=5),
    ),
    "JB-782503": (
        SeedAvailability(location_id="portfolio_network", status="sold_out", quantity=0),
    ),
    "JB-840569": (
        SeedAvailability(location_id="portfolio_network", status="in_stock", quantity=4),
    ),
    "SCORP-126560": (
        SeedAvailability(location_id="portfolio_network", status="in_stock", quantity=2),
    ),
    "SCORP-C07NXPT": (
        SeedAvailability(location_id="portfolio_network", status="at_supplier", quantity=0),
    ),
    "JW-818845": (
        SeedAvailability(
            location_id="portfolio_network", status="built_to_order", quantity=0,
            lead_time_min_days=6, lead_time_max_days=8,
        ),
    ),
}


def _configuration_claims(item: ReviewedConfiguration) -> dict[str, tuple[Any, str | None]]:
    """Every material configuration field is an independently referenceable fact."""

    return {
        "manufacturer_part_number": (item.mpn, None),
        "retailer_sku": (item.retailer_sku, None),
        "form_factor": (item.form_factor, None),
        "mobility": (item.mobility, None),
        "device_class": (item.device_class, None),
        "operating_system": (item.os_edition, None),
        "gpu_class": (item.gpu_class, None),
        "gpu_vram_gb": (item.gpu_vram_gb, "GB"),
        "gpu_tgp_w": (item.gpu_tgp_w, "W"),
        "ram_gb": (item.ram_installed_gb, "GB"),
        "ram_ceiling_gb": (item.ram_ceiling_gb, "GB"),
        "ram_upgradeable": (item.ram_upgradeable, None),
        "storage_gb": (item.storage_gb, "GB"),
        "warranty_type": (item.warranty_type, None),
        "warranty_years": (item.warranty_years, "years"),
    }


def _ensure_configuration_observations(
    db, config: ProductConfiguration, item: ReviewedConfiguration,
) -> None:
    existing = {
        row.attribute_key
        for row in db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.configuration_id == config.id,
        )).scalars()
    }
    for attribute, (value, unit) in _configuration_claims(item).items():
        if attribute in existing or value is None:
            continue
        db.add(ProductEvidenceObservation(
            configuration_id=config.id,
            attribute_key=attribute,
            value_json={"value": value},
            unit=unit,
            claim_class="attested",
            evidence_status="observed",
            source_id=item.retailer,
            source_record_id=f"{item.source_url}#spec-{attribute}",
            observed_at=item.reviewed_at,
        ))


def _ensure_official_observations(
    db, config: ProductConfiguration, item: ReviewedConfiguration,
) -> None:
    """Append exact OEM observations; family pages never certify a retailer SKU."""
    if item.official_identity_scope != "exact_configuration" or not item.official_source_url:
        return
    official_reviewed_at = item.official_reviewed_at or OEM_REVIEW_DATE
    config.specification_observed_at = official_reviewed_at
    rows = [
        SeedClaim(attribute_key="manufacturer_part_number", value=item.mpn, claim_class="attested"),
        *item.official_claims,
    ]
    existing = {
        row.source_record_id
        for row in db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.configuration_id == config.id,
        )).scalars()
    }
    for index, claim in enumerate(rows):
        record_id = f"{item.official_source_url}#exact-{index}-{claim.attribute_key}"
        if record_id in existing:
            continue
        db.add(ProductEvidenceObservation(
            configuration_id=config.id, attribute_key=claim.attribute_key,
            value_json={"value": claim.value}, unit=claim.unit,
            claim_class=claim.claim_class, evidence_status=claim.status,
            conflict_group=claim.conflict_group, source_id=item.manufacturer,
            source_record_id=record_id, source_excerpt=claim.excerpt,
            observed_at=official_reviewed_at,
        ))


def _ensure_availability_observations(
    db, config: ProductConfiguration, item: ReviewedConfiguration, *,
    inventory_profile: str | None = None,
) -> None:
    """Upsert deterministic portfolio stock without multiplying observations."""

    existing = {
        row.source_record_id: row
        for row in db.execute(select(ProductAvailabilityObservation).where(
            ProductAvailabilityObservation.configuration_id == config.id,
        )).scalars()
    }
    observations = [
        (f"{item.source_url}#availability-{index}", availability, item.reviewed_at)
        for index, availability in enumerate(item.availability)
    ]
    if inventory_profile == "realistic":
        observed_at = datetime.now(timezone.utc)
        observations.extend(
            (
                f"portfolio-demo://inventory/{item.sku}/{index}",
                availability,
                observed_at,
            )
            for index, availability in enumerate(PORTFOLIO_DEMO_AVAILABILITY.get(item.sku, ()))
        )
    for source_record_id, availability, observed_at in observations:
        row = existing.get(source_record_id)
        values = availability.model_dump()
        if row is None:
            db.add(ProductAvailabilityObservation(
                configuration_id=config.id, source_record_id=source_record_id,
                observed_at=observed_at, **values,
            ))
            continue
        for key, value in values.items():
            setattr(row, key, value)
        row.observed_at = observed_at


def configuration_hash(item: ReviewedConfiguration) -> str:
    material = item.model_dump(exclude={
        "claims", "availability", "official_claims", "official_source_url",
        "official_identity_scope", "official_reviewed_at", "reviewed_at",
    })
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def ingest_reviewed_configurations(
    db, *, tenant_id: str = "default", inventory_profile: str | None = None,
) -> list[str]:
    """Idempotently ingest the reviewed five-record fixture."""
    inventory_profile = inventory_profile or os.getenv("PORTFOLIO_DEMO_INVENTORY_PROFILE") or None
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
            _ensure_configuration_observations(db, existing, item)
            _ensure_official_observations(db, existing, item)
            _ensure_availability_observations(
                db, existing, item, inventory_profile=inventory_profile,
            )
            ids.append(existing.id)
            continue
        config = ProductConfiguration(
            tenant_id=tenant_id, product_id=product.id, configuration_hash=digest,
            specification_observed_at=item.reviewed_at, price_observed_at=item.reviewed_at,
            availability_observed_at=item.reviewed_at, currency="AUD", active=True,
            **item.model_dump(exclude={
                "claims", "availability", "official_claims", "official_source_url",
                "official_identity_scope", "official_reviewed_at", "reviewed_at",
            }),
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
                observed_at=item.reviewed_at,
            ))
        db.flush()
        _ensure_configuration_observations(db, config, item)
        _ensure_official_observations(db, config, item)
        _ensure_availability_observations(
            db, config, item, inventory_profile=inventory_profile,
        )
        ids.append(config.id)
    db.commit()
    return ids


__all__ = [
    "PORTFOLIO_DEMO_AVAILABILITY", "REVIEWED_CONFIGURATIONS",
    "configuration_hash", "ingest_reviewed_configurations",
]
