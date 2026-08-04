"""Enterprise approval-tier gate — spend routes a purchase to the right approver level."""
from __future__ import annotations

from src.app.services.fulfillment.approval_policy import (
    approver_can_clear, approver_level, required_approval_tier)

# explicit bands so the test is independent of the active StoreProfile
_TIERS = [
    {"max_cents": 100000, "tier": "auto", "min_level": 1},
    {"max_cents": 1000000, "tier": "manager", "min_level": 2},
    {"max_cents": 10000000, "tier": "director", "min_level": 3},
    {"max_cents": None, "tier": "executive", "min_level": 4},
]


def test_required_tier_climbs_with_spend():
    assert required_approval_tier(50000, tiers=_TIERS)["tier"] == "auto"        # $500
    assert required_approval_tier(100000, tiers=_TIERS)["tier"] == "auto"       # $1,000 (boundary inclusive)
    assert required_approval_tier(500000, tiers=_TIERS)["tier"] == "manager"    # $5,000
    assert required_approval_tier(5000000, tiers=_TIERS)["tier"] == "director"  # $50,000
    assert required_approval_tier(50000000, tiers=_TIERS)["tier"] == "executive"  # $500,000 (top band)
    assert required_approval_tier(50000000, tiers=_TIERS)["min_level"] == 4


def test_required_tier_handles_bad_input():
    assert required_approval_tier(None, tiers=_TIERS)["tier"] == "auto"
    assert required_approval_tier("oops", tiers=_TIERS)["value_cents"] == 0


def test_approver_level_default_map():
    assert approver_level("owner") >= approver_level("merchant")
    assert approver_level("unknown_role") == 0


def test_approver_can_clear_gates_by_level():
    # a merchant (level 2) can clear a manager-tier spend but NOT a director-tier spend
    ok_manager = approver_can_clear("merchant", 500000)      # $5,000 → manager
    assert ok_manager["ok"] is True
    blocked = approver_can_clear("merchant", 5000000)        # $50,000 → director
    assert blocked["ok"] is False
    assert blocked["required_tier"] == "director" and "below required" in blocked["reason"]
    # owner clears the top tier
    assert approver_can_clear("owner", 50000000)["ok"] is True
