from __future__ import annotations

from datetime import datetime, timezone

from src.app.services.connectors.product_capability_evidence import (
    ProductCapabilityEvidence,
    ProductCapabilityEvidenceRegistry,
    ProductIdentity,
    ProductSourcePolicy,
    identity_from_catalog_variant,
    load_product_source_policies,
)


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
