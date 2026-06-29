"""Bounded-autonomy buyer status reply: a claim-safe, commitment-free message per case state, so the
buyer always knows where their bulk request stands. Never contains a price/commitment (defense-in-depth)."""
from __future__ import annotations

import pytest

from src.app.services.fulfillment.buyer_reply import buyer_status_message

_CS = {"availability": {"requested_qty": 50}}


@pytest.mark.parametrize("state,needle", [
    ("AWAITING_BUYER_COMMITMENT", "Confirm sourcing"),
    ("COMMITTED", "no order has been placed"),
    ("QUOTE_SENT", "requested a quote"),
    ("OPTIONS_READY", "options are ready"),
    ("NO_APPROVED_SUPPLIER", "alternatives"),
    ("BUYER_DECLINED", "closed"),
])
def test_status_message_per_state(state, needle):
    msg = buyer_status_message(state, _CS)
    assert needle.lower() in msg.lower()


def test_includes_quantity_when_known():
    assert "50 units" in buyer_status_message("AWAITING_BUYER_COMMITMENT", _CS)


def test_never_contains_price_or_commitment():
    for state in ("AWAITING_BUYER_COMMITMENT", "COMMITTED", "QUOTE_SENT", "QUOTE_VALIDATED",
                  "OPTIONS_READY", "COMPLETED", "NO_APPROVED_SUPPLIER"):
        m = buyer_status_message(state, _CS).lower()
        assert "$" not in m and "guarantee" not in m and "purchase order" not in m


def test_unknown_state_is_empty():
    assert buyer_status_message("SOME_INTERNAL_STATE", _CS) == ""
    assert buyer_status_message(None, None) == ""
