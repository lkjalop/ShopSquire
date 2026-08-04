"""Shipping-address validation — the format/plausibility gate that closes the 'accepts any string'
gap at checkout + plan-confirm. Severity, not a hard boolean, so checkout isn't brittle."""
from __future__ import annotations

import pytest

from src.app.services.address_validation import validate_address


@pytest.mark.parametrize("addr", ["", "   ", "12 St", "laptopspls"])
def test_unusable_addresses_reject(addr):
    v = validate_address(addr)
    assert v["severity"] == "reject" and v["valid"] is False


def test_full_au_address_ok():
    v = validate_address("12 Smith St, Sydney NSW 2000")
    assert v["severity"] == "ok" and v["has_postcode"] is True and v["country"] == "AU"


def test_plausible_but_no_postcode_warns():
    v = validate_address("12 Smith Street, Sydney NSW")
    assert v["severity"] == "warn" and v["valid"] is True and v["has_postcode"] is False


def test_country_specific_postcode():
    assert validate_address("100 Main St, Springfield IL 62704", country="US")["severity"] == "ok"
    assert validate_address("221B Baker Street, London NW1 6XE", country="GB")["severity"] == "ok"
    # a US 5-digit zip is NOT a valid AU 4-digit → warn under AU rules (no AU postcode signal)
    assert validate_address("100 Main St, Somewhere 62704", country="AU")["has_postcode"] is False


def test_provider_flag_does_not_silently_pass(monkeypatch):
    # enabling a provider that isn't wired must fall through to the heuristic, not auto-approve
    monkeypatch.setenv("ADDRESS_VALIDATION_PROVIDER", "auspost")
    assert validate_address("")["severity"] == "reject"
