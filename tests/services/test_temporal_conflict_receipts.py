from src.app.services.temporal_conflicts import (
    TemporalClaim,
    detect_temporal_conflicts,
)


def test_conflicting_supplier_and_carrier_lead_times_remain_unresolved():
    conflicts = detect_temporal_conflicts([
        TemporalClaim(
            claim_id="supplier-eight", subject="offer:preferred", attribute="lead_time_days",
            value=8, valid_from="2026-08-17T00:00:00+00:00",
            valid_to="2026-08-30T00:00:00+00:00",
            observed_at="2026-08-17T01:00:00+00:00", source="supplier-a",
            source_authority="supplier_attested",
        ),
        TemporalClaim(
            claim_id="carrier-twelve", subject="offer:preferred", attribute="lead_time_days",
            value=12, valid_from="2026-08-17T00:00:00+00:00",
            valid_to="2026-08-30T00:00:00+00:00",
            observed_at="2026-08-17T02:00:00+00:00", source="carrier-a",
            source_authority="carrier_observed",
        ),
    ])
    assert len(conflicts) == 1
    receipt = conflicts[0]
    assert receipt.competing_claim_ids == ("carrier-twelve", "supplier-eight")
    assert receipt.status == "unresolved"
    assert receipt.resolution_owner == "supplier"
    assert receipt.affected_stages == ("commercial", "fulfilment", "response")


def test_newer_lower_authority_claim_does_not_automatically_win():
    conflicts = detect_temporal_conflicts([
        TemporalClaim(
            claim_id="oem", subject="configuration:a", attribute="ram_gb", value=64,
            valid_from="2026-08-01T00:00:00+00:00", observed_at="2026-08-01T00:00:00+00:00",
            source="oem", source_authority="oem_attested",
        ),
        TemporalClaim(
            claim_id="new-snippet", subject="configuration:a", attribute="ram_gb", value=32,
            valid_from="2026-08-01T00:00:00+00:00", observed_at="2026-08-16T00:00:00+00:00",
            source="search-snippet", source_authority="discovery_snippet",
        ),
    ])
    assert conflicts[0].status == "unresolved"
    assert conflicts[0].resolution_owner == "research"


def test_nonoverlapping_temporal_values_do_not_conflict():
    conflicts = detect_temporal_conflicts([
        TemporalClaim(
            claim_id="old", subject="sku:a", attribute="price_minor", value=100,
            valid_from="2026-08-01T00:00:00+00:00", valid_to="2026-08-10T00:00:00+00:00",
            observed_at="2026-08-01T00:00:00+00:00", source="retailer",
        ),
        TemporalClaim(
            claim_id="new", subject="sku:a", attribute="price_minor", value=120,
            valid_from="2026-08-10T00:00:00+00:00",
            observed_at="2026-08-10T00:00:00+00:00", source="retailer",
        ),
    ])
    assert conflicts == ()
