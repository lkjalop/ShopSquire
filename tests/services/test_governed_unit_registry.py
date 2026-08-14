from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.app.services.governed_unit_registry import (
    FxRateEvidence, convert_currency, convert_measurement,
)


def test_reviewed_storage_duration_and_quantity_conversions():
    assert convert_measurement(2, "TB", "GB").output_value == Decimal("2000")
    assert convert_measurement(48, "hour", "day").output_value == Decimal("2")
    assert convert_measurement(30, "each", "unit").output_value == Decimal("30")


def test_decimal_storage_does_not_silently_cross_binary_memory_dimension():
    with pytest.raises(ValueError, match="unit_dimension_mismatch"):
        convert_measurement(32, "GB", "GiB")


def test_cross_currency_requires_current_timestamped_authority():
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timestamped_fx_rate_required"):
        convert_currency(100, "AUD", "USD", now=now)
    stale = FxRateEvidence(
        base_currency="AUD", quote_currency="USD", rate=Decimal("0.65"),
        observed_at=now - timedelta(days=2), source_authority="fx-authority",
        source_record_id="rate-1",
    )
    with pytest.raises(ValueError, match="fx_rate_stale"):
        convert_currency(100, "AUD", "USD", rate_evidence=stale, now=now)
    fresh = stale.model_copy(update={"observed_at": now - timedelta(hours=1)})
    receipt = convert_currency(100, "AUD", "USD", rate_evidence=fresh, now=now)
    assert receipt.output_value == Decimal("65.00") and receipt.method == "timestamped_fx"
