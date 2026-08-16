import pytest
from pydantic import ValidationError

from src.app.services.evidence_measurements import EvidenceMeasurement


def test_zero_is_a_real_observation_but_missing_cannot_carry_zero():
    observed = EvidenceMeasurement(metric="stock", state="observed", value=0, unit="units")
    assert observed.value == 0
    with pytest.raises(ValidationError, match="missing_measurement_cannot_have_value"):
        EvidenceMeasurement(metric="stock", state="not_disclosed", value=0, unit="units")


def test_rate_requires_honest_paired_denominator():
    with pytest.raises(ValidationError, match="rate_counts_must_be_paired"):
        EvidenceMeasurement(metric="conversion", state="derived", value=0.2, numerator=2)


def test_empty_unavailable_stale_and_undisclosed_are_distinct_states():
    empty = EvidenceMeasurement(metric="offers", state="empty")
    unavailable = EvidenceMeasurement(metric="offers", state="unavailable")
    undisclosed = EvidenceMeasurement(metric="capacity", state="not_disclosed")
    stale = EvidenceMeasurement(metric="stock", state="stale", value=4, unit="units")

    assert {empty.state, unavailable.state, undisclosed.state, stale.state} == {
        "empty", "unavailable", "not_disclosed", "stale",
    }
