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
    assert len(reviewed.accepted) == 4
