"""Capability registry (B1) — the declared-boundary facts that keep the narrator honest.

Covers: topic-gated emission (payment plans / financing / leasing / trade-in), the
autonomy-limit money trigger, backorder-consent trigger, custom vertical entries,
silence when the profile declares nothing, and the fail-safe on malformed patterns."""
from __future__ import annotations

from src.app.services.capability_registry import (
    _max_amount,
    capability_preamble_note,
    get_capabilities,
)

CAPS = {
    "does_not_offer": ["payment_plans", "in_house_financing", "leasing", "trade_in"],
    "payment_methods": ["credit/debit card", "PayPal"],
    "autonomy_limits": {"max_autonomous_order_value_usd": 20000},
    "fulfilment": {"backorder": True, "typical_reorder_days": 7},
    "custom": {},
}


def _note(query, caps=CAPS, monkeypatch=None):
    import src.app.services.capability_registry as mod
    orig = mod.get_capabilities
    mod.get_capabilities = lambda profile_id=None: caps
    try:
        return capability_preamble_note(query)
    finally:
        mod.get_capabilities = orig


def test_payment_plan_phrasings_all_hit():
    for q in (
        "do you offer payment plans or financing?",
        "can I pay monthly for this?",
        "is afterpay or klarna available?",
        "any instalment options?",
    ):
        note = _note(q)
        assert note and "does NOT offer" in note, q
        assert "payment plans" in note
        assert "third-party retailers" in note  # the anti-"check Best Buy" instruction
        assert "credit/debit card" in note      # honest positive: what IS accepted


def test_autonomy_limit_fires_on_amount_at_or_over():
    note = _note("i want to spend around 25000 on machines for my team — payment plans?")
    assert note and "human account manager" in note and "$20,000" in note
    # $25k shorthand too
    assert "human account manager" in _note("budget is $25k for the fleet, financing?")


def test_autonomy_limit_silent_under_threshold():
    note = _note("do you offer payment plans? budget 3500")
    assert note and "human account manager" not in note


def test_backorder_only_on_availability_phrasing():
    note = _note("i need 50 dell laptops but you only have a few in stock — ok waiting for a reorder?")
    assert note and "backordered" in note and "~7 days" in note and "consent" in note
    assert _note("what is the best gaming laptop?") is None


def test_no_slot_means_silence_not_invented_policy():
    assert _note("do you offer payment plans?", caps={}) is None


def test_custom_vertical_entry_and_malformed_pattern_failsafe():
    caps = dict(CAPS)
    caps["custom"] = {
        "rx": {"pattern": "prescription", "statement": "Prescription items require verification."},
        "broken": {"pattern": "([unclosed", "statement": "never emitted"},
    }
    note = _note("can i buy prescription meds without a script?", caps=caps)
    assert note and "Prescription items require verification." in note
    assert "never emitted" not in note


def test_money_parser():
    assert _max_amount("spend 25,000 dollars") == 25000
    assert _max_amount("about $25k total") == 25000
    assert _max_amount("a 3500 budget") == 3500
    assert _max_amount("no numbers here") == 0


def test_live_electronics_profile_declares_the_boundary():
    caps = get_capabilities("electronics")
    assert "payment_plans" in (caps.get("does_not_offer") or [])
    assert caps.get("autonomy_limits", {}).get("max_autonomous_order_value_usd") == 20000
