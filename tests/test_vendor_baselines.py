"""Tests for per-vendor invoice baseline and anomaly detection."""
import pytest

from src.app.security.vendor_baselines import (
    check_anomaly,
    clear_all,
    get_baseline,
    list_vendors,
    record_invoice,
)


@pytest.fixture(autouse=True)
def _reset():
    clear_all()
    yield
    clear_all()


def test_record_and_baseline():
    for amt in [1000, 1100, 900, 1050, 950]:
        record_invoice("acme.com", amt)

    bl = get_baseline("acme.com")
    assert bl is not None
    assert bl["count"] == 5
    assert bl["mean"] == 1000.0  # exact average of symmetric values
    assert bl["std"] > 0


def test_insufficient_data():
    record_invoice("new.com", 500)
    assert get_baseline("new.com") is None
    result = check_anomaly("new.com", 500)
    assert result["anomaly"] is False
    assert "Insufficient" in result["reason"]


def test_anomaly_detected():
    # Build a tight baseline around $1000
    for _ in range(10):
        record_invoice("tight.com", 1000.0)
    # Expect $47k to be flagged
    result = check_anomaly("tight.com", 47272.50)
    assert result["anomaly"] is True
    assert result["z_score"] > 2.0
    assert "$47,272.50" in result["reason"]


def test_normal_amount():
    for amt in [1000, 1100, 900, 1050, 950]:
        record_invoice("normal.com", amt)
    result = check_anomaly("normal.com", 1020)
    assert result["anomaly"] is False


def test_list_vendors():
    record_invoice("a.com", 100)
    record_invoice("b.com", 200)
    vendors = list_vendors()
    assert "a.com" in vendors
    assert "b.com" in vendors


def test_zero_std():
    """All identical amounts → std=0 → same amount is normal, different is anomaly."""
    for _ in range(5):
        record_invoice("flat.com", 500.0)
    assert check_anomaly("flat.com", 500.0)["anomaly"] is False
    assert check_anomaly("flat.com", 600.0)["anomaly"] is True
