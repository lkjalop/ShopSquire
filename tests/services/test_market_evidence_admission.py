"""Explicit source validity must never degrade into an inferred valid interval."""
from datetime import datetime, timezone

import pytest

from src.app.services.market_evidence_admission import market_evidence_admission

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def finding(**overrides):
    return {"status": "observed", "source_system": "owned-test", "source_record_id": "quote-1",
            "lineage_root": "supplier-quote", "provenance_chain": ["reviewed-quote-1"],
            "observed_at": "2026-10-24T10:00:00Z", "effective_to": "2026-10-25T10:00:00Z",
            **overrides}


@pytest.mark.parametrize("explicit", ["not-a-date", "", "2026-99-99", {}, False])
def test_malformed_explicit_start_cannot_fall_back_to_observation(explicit):
    assert market_evidence_admission(finding(effective_from=explicit), now=NOW) == "validity_invalid"


@pytest.mark.parametrize("overrides", [{}, {"effective_from": None},
    {"effective_from": "2026-10-24T09:00:00Z"},
    {"effective_from": "2026-10-24T21:00:00+11:00"}])
def test_missing_null_or_valid_start_retains_current_positive(overrides):
    assert market_evidence_admission(finding(**overrides), now=NOW) is None


@pytest.mark.parametrize("field", ["published_at", "available_at"])
@pytest.mark.parametrize("explicit, expected", [("bad-date", "source_time_invalid"),
    ("", "source_time_invalid"), ("2026-10-24T12:00:01Z", "evidence_not_current"),
    ("2026-10-24T11:00:00Z", None), (None, None)])
def test_source_availability_is_admitted_independently(field, explicit, expected):
    assert market_evidence_admission(finding(**{field: explicit}), now=NOW) == expected


@pytest.mark.parametrize("overrides, expected", [
    ({"observed_at": "2026-10-24T12:00:01Z"}, "evidence_not_current"),
    ({"effective_from": "2026-10-24T12:00:01Z"}, "evidence_not_current"),
    ({"effective_to": "2026-10-24T12:00:00Z"}, "evidence_not_current"),
    ({"effective_from": "2026-10-24T10:00:00Z", "effective_to": "2026-10-24T10:00:00Z"}, "evidence_not_current"),
    ({"effective_to": "bad-date"}, "validity_missing"),
    ({"source_record_id": None}, "provenance_incomplete"),
    ({"status": "proposed"}, "not_observed"),
])
def test_existing_temporal_and_provenance_rejections_remain(overrides, expected):
    assert market_evidence_admission(finding(**overrides), now=NOW) == expected
