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
