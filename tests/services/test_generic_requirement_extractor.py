from datetime import datetime, timezone

from src.app.services.generic_requirement_extractor import (
    critique_extracted_requirements,
    extract_generic_requirements,
)


def test_generic_extractor_retains_exact_citation_span_and_typed_values():
    text = "Minimum: 32 GB RAM. Recommended: 2 TB NVMe storage."
    claims = extract_generic_requirements(
        text, citation_url="https://vendor.example/requirements",
        observed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    assert [(row.attribute, row.value) for row in claims] == [
        ("ram_gb", 32), ("storage_gb", 2000),
    ]
    reviewed = critique_extracted_requirements(
        claims, source_text=text, accepted_url="https://vendor.example/requirements",
        allowed_attributes={"ram_gb", "storage_gb"},
    )
    assert len(reviewed.accepted) == 2
    assert reviewed.rejected == []


def test_critic_rejects_wrong_origin_forbidden_and_unsupported_span():
    source = "Minimum: 32 GB RAM."
    claims = extract_generic_requirements(
        source, citation_url="https://wrong.example/requirements",
        observed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    reviewed = critique_extracted_requirements(
        claims, source_text=source, accepted_url="https://vendor.example/requirements",
        forbidden_attributes={"ram_gb"},
    )
    assert reviewed.accepted == []
    assert reviewed.rejected[0]["reason"] == "citation_origin_mismatch"


def test_generic_extractor_preserves_distinct_html_style_requirement_tiers():
    text = (
        "Minimum Specs\nMemory: 16 GB RAM\nStorage: 130 GB SSD storage\n"
        "Recommended Specs\nMemory: 32 GB RAM\nStorage: 200 GB SSD storage"
    )
    claims = extract_generic_requirements(
        text, citation_url="https://publisher.example/install-guide",
        observed_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert {
        (row.attribute, row.value, row.requirement_class)
        for row in claims
    } >= {
        ("ram_gb", 16, "minimum"),
        ("ram_gb", 32, "recommended"),
        ("storage_gb", 130, "minimum"),
        ("storage_gb", 200, "recommended"),
    }
    reviewed = critique_extracted_requirements(
        claims, source_text=text,
        accepted_url="https://publisher.example/install-guide",
    )
    assert len(reviewed.accepted) == 6
    assert [
        (row.value, row.requirement_class)
        for row in reviewed.accepted if row.attribute == "storage_type"
    ] == [("SSD", "minimum"), ("SSD", "recommended")]


def test_generic_extractor_retains_labelled_models_platform_and_performance_targets():
    text = (
        "Recommended requirements\n"
        "Processor: Intel Core i7-12700K or AMD Ryzen 7 5800X\n"
        "Graphics: NVIDIA GeForce RTX 4070 or AMD Radeon RX 7800 XT\n"
        "Operating system: Windows 11 64-bit\n"
        "Storage: 1 TB NVMe SSD\n"
        "Graphics API: DirectX 12 or Vulkan 1.3\n"
        "Architecture: x86-64\n"
        "Display target: 2560 x 1440 at 60 FPS\n"
        "Advanced projects: 50,000 images"
    )
    claims = extract_generic_requirements(
        text, citation_url="https://publisher.example/system-requirements",
        observed_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    by_attribute = {row.attribute: row for row in claims}
    assert by_attribute["cpu_model"].value == (
        "Intel Core i7-12700K or AMD Ryzen 7 5800X"
    )
    assert by_attribute["gpu_model"].value == (
        "NVIDIA GeForce RTX 4070 or AMD Radeon RX 7800 XT"
    )
    assert by_attribute["operating_system"].value == "Windows 11 64-bit"
    assert by_attribute["storage_type"].value == "NVMe SSD"
    assert by_attribute["api_compatibility"].value == ["DirectX 12", "Vulkan 1.3"]
    assert by_attribute["architecture_compatibility"].value == "x86-64"
    assert by_attribute["resolution"].value == "2560x1440"
    assert by_attribute["fps"].value == 60
    assert by_attribute["project_scale"].value == 50000
    assert all(row.requirement_class in {"recommended", "conditional"} for row in claims)

    reviewed = critique_extracted_requirements(
        claims, source_text=text,
        accepted_url="https://publisher.example/system-requirements",
    )
    assert len(reviewed.accepted) == len(claims)
    assert reviewed.rejected == []


def test_generic_critic_rejects_conflicting_values_within_one_requirement_tier():
    source = "Minimum requirements\nMemory: 16 GB RAM\nMemory: 32 GB RAM"
    claims = extract_generic_requirements(
        source, citation_url="https://publisher.example/requirements",
        observed_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    reviewed = critique_extracted_requirements(
        claims, source_text=source,
        accepted_url="https://publisher.example/requirements",
    )
    assert len(reviewed.accepted) == 1
    assert reviewed.rejected == [{"attribute": "ram_gb", "reason": "contradictory_claim"}]
