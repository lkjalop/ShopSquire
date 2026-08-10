from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.app.models.orm import Base, ProductConfiguration, ProductEvidenceObservation
from src.app.services.connectors.product_capability_evidence import (
    AsusOfficialHtmlProductProvider,
    ProductCapabilityEvidence,
    ProductCapabilityEvidenceRegistry,
    ProductIdentity,
    ProductSourcePolicy,
    identity_from_catalog_variant,
    load_product_source_policies,
)
from src.app.services.product_capability_refresh import refresh_exact_configuration_capabilities


class _Provider:
    provider_id = "manufacturer-spec"
    source_types = ("manufacturer_product_spec",)

    def __init__(self, evidence):
        self.evidence = evidence

    def resolve(self, identity, *, claim_keys, allow_live):
        return self.evidence


def _evidence(**overrides):
    base = {
        "provider_id": "manufacturer-spec",
        "source_type": "manufacturer_product_spec",
        "publisher": "Example Manufacturer",
        "source_url": "https://specs.example.test/products/21KX0001AU",
        "source_record_id": "21KX0001AU",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "identity": ProductIdentity(
            sku="SKU-A", identifier_type="manufacturer_part_number",
            identifier="21KX0001AU",
        ),
        "claims": (
            {"attribute_key": "ram_gb", "value": 32, "unit": "GB", "confidence": 0.99},
        ),
    }
    base.update(overrides)
    return ProductCapabilityEvidence(**base)


def test_registry_accepts_identity_bound_allowlisted_official_claims():
    registry = ProductCapabilityEvidenceRegistry(
        providers=[_Provider(_evidence())],
        policies=[ProductSourcePolicy(
            provider_id="manufacturer-spec",
            allowed_publishers=("Example Manufacturer",),
            allowed_domains=("specs.example.test",),
            max_age_seconds=86400,
        )],
    )

    result = registry.resolve(
        ProductIdentity("SKU-A", "manufacturer_part_number", "21KX0001AU"),
        claim_keys=("ram_gb", "gpu_vram_gb"), allow_live=True,
    )

    assert result.status == "accepted"
    assert result.accepted_claims[0]["attribute_key"] == "ram_gb"
    assert result.unknown_claim_keys == ("gpu_vram_gb",)
    assert result.attempts[0]["status"] == "accepted"


def test_registry_rejects_identity_mismatch_and_poisoned_publisher():
    wrong_identity = _evidence(identity=ProductIdentity(
        sku="SKU-B", identifier_type="manufacturer_part_number", identifier="OTHER",
    ))
    registry = ProductCapabilityEvidenceRegistry(
        providers=[_Provider(wrong_identity)],
        policies=[ProductSourcePolicy(
            provider_id="manufacturer-spec",
            allowed_publishers=("Example Manufacturer",),
            allowed_domains=("specs.example.test",),
        )],
    )
    result = registry.resolve(
        ProductIdentity("SKU-A", "manufacturer_part_number", "21KX0001AU"),
        claim_keys=("ram_gb",), allow_live=True,
    )
    assert result.status == "rejected"
    assert result.attempts[0]["reason"] == "product_identity_mismatch"

    poisoned = _evidence(publisher="Untrusted Reseller")
    registry = ProductCapabilityEvidenceRegistry(
        providers=[_Provider(poisoned)],
        policies=[ProductSourcePolicy(
            provider_id="manufacturer-spec",
            allowed_publishers=("Example Manufacturer",),
            allowed_domains=("specs.example.test",),
        )],
    )
    result = registry.resolve(
        ProductIdentity("SKU-A", "manufacturer_part_number", "21KX0001AU"),
        claim_keys=("ram_gb",), allow_live=True,
    )
    assert result.status == "rejected"
    assert result.attempts[0]["reason"] == "publisher_not_allowed"


def test_conflicting_official_claims_are_not_silently_selected():
    first = _Provider(_evidence())
    second = _Provider(_evidence(
        provider_id="component-spec",
        publisher="Component Vendor",
        source_url="https://ark.example.test/items/cpu-1",
        claims=({"attribute_key": "ram_gb", "value": 64, "unit": "GB", "confidence": 0.98},),
    ))
    second.provider_id = "component-spec"
    registry = ProductCapabilityEvidenceRegistry(
        providers=[first, second],
        policies=[
            ProductSourcePolicy("manufacturer-spec", ("Example Manufacturer",), ("specs.example.test",)),
            ProductSourcePolicy("component-spec", ("Component Vendor",), ("ark.example.test",)),
        ],
    )
    result = registry.resolve(
        ProductIdentity("SKU-A", "manufacturer_part_number", "21KX0001AU"),
        claim_keys=("ram_gb",), allow_live=True,
    )
    assert result.status == "conflict"
    assert result.accepted_claims == ()
    assert result.conflicts[0]["attribute_key"] == "ram_gb"


def test_official_source_enrollment_is_data_driven():
    policies = {item.provider_id: item for item in load_product_source_policies()}
    assert "lenovo_psref" in policies
    assert "psref.lenovo.com" in policies["lenovo_psref"].allowed_domains
    assert "intel_ark" in policies
    assert "nvidia_product_specs" in policies


def test_catalog_identity_uses_mtm_then_mpn_gtin_family_and_title():
    class _Variant:
        sku = "SKU-A"
        title = "Verbose title"
        specs = {
            "mtm": "21KX0001AU",
            "mpn": "MPN-2",
            "gtin": "09312345678901",
            "family": "Family A",
        }

    identity = identity_from_catalog_variant(_Variant())
    assert identity.identifier_type == "machine_type_model"
    assert identity.identifier == "21KX0001AU"
    assert len(identity.configuration_hash) == 64


def test_same_mpn_with_conflicting_configuration_hash_is_rejected():
    expected = ProductIdentity(
        "SKU-A", "manufacturer_part_number", "21KX0001AU",
        configuration_hash="a" * 64, form_factor="laptop",
    )
    actual = ProductIdentity(
        "SKU-A", "manufacturer_part_number", "21KX0001AU",
        configuration_hash="b" * 64, form_factor="laptop",
    )
    registry = ProductCapabilityEvidenceRegistry(
        providers=[_Provider(_evidence(identity=actual))],
        policies=[ProductSourcePolicy(
            "manufacturer-spec", ("Example Manufacturer",), ("specs.example.test",),
        )],
    )
    result = registry.resolve(expected, claim_keys=("ram_gb",), allow_live=True)
    assert result.status == "rejected"
    assert result.attempts[0]["reason"] == "product_identity_mismatch"


def test_title_fallback_cannot_authorize_configuration_claims():
    title_identity = ProductIdentity("SKU-A", "title", "Mobile Workstation")
    evidence = _evidence(identity=title_identity)
    registry = ProductCapabilityEvidenceRegistry(
        providers=[_Provider(evidence)],
        policies=[ProductSourcePolicy(
            "manufacturer-spec", ("Example Manufacturer",), ("specs.example.test",),
        )],
    )
    result = registry.resolve(
        title_identity, claim_keys=("ram_gb",), allow_live=True,
    )
    assert result.status == "rejected"
    assert result.attempts[0]["reason"] == "identity_type_not_allowed"


def test_asus_official_parser_binds_claims_to_the_exact_sku_column(monkeypatch):
    html = b"""
      <p class='ProductSpec__specProductName__x'>GX651AR-SR002W</p>
      <p class='ProductSpec__specProductName__x'>GX651AX-SR004W</p>
      <div class='ProductSpec__row__x'><h2>Operating System</h2><div>
        <div class='ProductSpec__rowItem__x'>Windows 11 Home</div>
        <div class='ProductSpec__rowItem__x'>Windows 11 Pro</div>
      </div></div>
      <div class='ProductSpec__row__x'><h2>Graphics</h2><div>
        <div class='ProductSpec__rowItem__x'>NVIDIA GeForce RTX 5070 Ti Laptop GPU 12GB GDDR7</div>
        <div class='ProductSpec__rowItem__x'>NVIDIA GeForce RTX 5090 Laptop GPU 24GB GDDR7</div>
      </div></div>
      <div class='ProductSpec__row__x'><h2>Memory</h2><div>
        <div class='ProductSpec__rowItem__x'>32GB LPDDR5X - Max Capacity : 64GB Memory Slot: No expansion possible</div>
        <div class='ProductSpec__rowItem__x'>64GB LPDDR5X - Max Capacity : 64GB Memory Slot: No expansion possible</div>
      </div></div>
      <div class='ProductSpec__row__x'><h2>Storage</h2><div>
        <div class='ProductSpec__rowItem__x'>1TB PCIe NVMe SSD</div>
        <div class='ProductSpec__rowItem__x'>2TB PCIe NVMe SSD</div>
      </div></div>
    """

    class _Response:
        content = html
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

    class _Client:
        @staticmethod
        def get(*args, **kwargs):
            return _Response()

    monkeypatch.setattr(
        "src.app.security.url_guard.validate_outbound_url",
        lambda _url: (True, "allowed"),
    )
    identity = ProductIdentity(
        sku="SCORP-125638", identifier_type="manufacturer_part_number",
        identifier="GX651AX-SR004W", configuration_hash="a" * 64, form_factor="laptop",
    )
    provider = AsusOfficialHtmlProductProvider(
        "asus_official_specs", endpoint="https://rog.asus.com/au/example/spec/", client=_Client,
    )
    evidence = provider.resolve(
        identity,
        claim_keys=("operating_system", "gpu_vram_gb", "ram_gb", "storage_gb"),
        allow_live=True,
    )

    assert evidence is not None
    claims = {row["attribute_key"]: row["value"] for row in evidence.claims}
    assert claims == {
        "operating_system": "Windows 11 Pro",
        "gpu_vram_gb": 24,
        "ram_gb": 64,
        "storage_gb": 2000,
    }
    assert evidence.parser_id == "asus_official_spec_columns_v1"
    assert evidence.http_status == 200
    assert len(evidence.response_body_sha256) == 64


def test_live_spec_refresh_appends_conflict_without_refreshing_price_or_availability():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    old = datetime(2026, 7, 1, tzinfo=timezone.utc)
    retrieved = datetime.now(timezone.utc).isoformat()
    with Session(engine) as db:
        configuration = ProductConfiguration(
            tenant_id="default", sku="SCORP-125638", title="ASUS Duo",
            manufacturer="ASUS", mpn="GX651AX-SR004W", retailer="Scorptec",
            configuration_hash="a" * 64, form_factor="laptop", mobility="mobile",
            device_class="consumer_gaming_flagship", price_cents=1_299_900,
            currency="AUD", specification_observed_at=old, price_observed_at=old,
            availability_observed_at=old, active=True,
        )
        db.add(configuration)
        db.flush()
        db.add(ProductEvidenceObservation(
            configuration_id=configuration.id, attribute_key="operating_system",
            value_json={"value": "Windows 11 Pro"}, claim_class="attested",
            evidence_status="observed", source_id="retailer",
            source_record_id="retailer:os", observed_at=old,
        ))
        evidence = ProductCapabilityEvidence(
            provider_id="asus_official_specs", source_type="manufacturer_product_spec",
            publisher="Republic of Gamers", source_url="https://rog.asus.com/au/example/spec/",
            source_record_id="GX651AX-SR004W:hash", retrieved_at=retrieved,
            identity=ProductIdentity(
                configuration.sku, "manufacturer_part_number", configuration.mpn,
                configuration.configuration_hash, "laptop",
            ),
            claims=({
                "attribute_key": "operating_system", "value": "Windows 11 Home",
                "confidence": 1.0, "claim_class": "attested",
            },),
        )
        provider = _Provider(evidence)
        provider.provider_id = "asus_official_specs"
        registry = ProductCapabilityEvidenceRegistry(
            providers=(provider,),
            policies=(ProductSourcePolicy(
                "asus_official_specs", ("Republic of Gamers",), ("rog.asus.com",),
                allowed_identity_types=("manufacturer_part_number",),
            ),),
            allowed_tenants=("default",),
        )

        report = refresh_exact_configuration_capabilities(
            db, configuration, registry=registry, claim_keys=("operating_system",),
        )
        observations = db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.configuration_id == configuration.id,
            ProductEvidenceObservation.attribute_key == "operating_system",
        )).scalars().all()

    assert report["observations_inserted"] == 1
    assert {row.value_json["value"] for row in observations} == {
        "Windows 11 Home", "Windows 11 Pro",
    }
    assert report["specification_observed_at"] != old.isoformat()
    assert report["price_observed_at"] == old.replace(tzinfo=None).isoformat()
    assert report["availability_observed_at"] == old.replace(tzinfo=None).isoformat()
