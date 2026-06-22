"""Regression: a statistically-detected hidden payload must never route to the
standard queue at green.

Graded against dump/test-sec/steg-test-manifest.json expectations: the C2-beacon
and payment-fraud carriers (tagged 'steganography_suspected') previously escalated
GREEN -> standard_queue because steganography_suspected was omitted from the
suspicion triggers and the escalation had no threat-class floor.
"""
from __future__ import annotations

import pytest

from src.app.routers.cv import _apply_threat_class_floor, _THREAT_FLOOR_TAGS


@pytest.mark.parametrize("tag", list(_THREAT_FLOOR_TAGS))
def test_threat_tag_floors_green_to_yellow(tag):
    assert _apply_threat_class_floor("green", [tag]) == "yellow"


def test_no_threat_tag_leaves_level_unchanged():
    assert _apply_threat_class_floor("green", ["product_identity_low_confidence"]) == "green"
    assert _apply_threat_class_floor("green", []) == "green"
    assert _apply_threat_class_floor("green", None) == "green"


def test_floor_never_lowers_a_higher_level():
    # Progressive escalation already at orange/red must not be pulled down to yellow.
    assert _apply_threat_class_floor("orange", ["steganography_suspected"]) == "orange"
    assert _apply_threat_class_floor("red", ["steganography_suspected"]) == "red"


def test_c2_beacon_and_payment_fraud_no_longer_green():
    # These manifest payloads surface as 'steganography_suspected'; they must floor
    # to at least yellow (i.e. leave the green/standard-queue path).
    for tag in ("steganography_suspected",):
        assert _apply_threat_class_floor("green", [tag]) != "green"
