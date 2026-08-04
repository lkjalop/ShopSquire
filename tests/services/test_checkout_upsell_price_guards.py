"""Phase 0b — checkout_upsell adaptive price-guard units (the cents-vs-dollars bug fix).

Pins that the guard treats cart/candidate prices as CENTS and that BOTH branches are live:
- substantial carts (> $200) cap upsells at 70% of cart,
- low-value carts (<= $200) allow upsells up to 1.9x,
- the old $12 (1200-cent) crossover that made the relaxed branch dead is gone.
"""
from __future__ import annotations

from src.app.services.checkout_upsell import (
    _ADAPTIVE_CART_CROSSOVER_CENTS,
    _passes_price_guard,
)


def test_crossover_is_in_cents_not_dollars():
    # $200, not $12 — the bug was treating 1200 cents as if it were $1200.
    assert _ADAPTIVE_CART_CROSSOVER_CENTS == 20000


def test_substantial_cart_caps_at_70pct():
    cart = 150000  # $1500 laptop
    assert _passes_price_guard(100000, cart) is True       # $1000 <= 70% ($1050)
    assert _passes_price_guard(110000, cart) is False      # $1100 > 70%
    # Laptop-cart behaviour is unchanged from the old (always-strict) code.


def test_low_value_cart_relaxed_branch_is_LIVE():
    # The whole point of the fix: a $50 accessory cart can be grown up to 1.9x ($95).
    cart = 5000  # $50
    assert _passes_price_guard(9000, cart) is True         # $90 <= 1.9x ($95)
    assert _passes_price_guard(10000, cart) is False       # $100 > 1.9x
    # Under the old 1200-cent crossover this cart was STRICT (>$12) and capped at $35 — the
    # relaxed branch never ran. Assert it now runs:
    assert _passes_price_guard(6000, cart) is True         # $60 (would be rejected by 70% rule)


def test_crossover_boundary():
    cart = _ADAPTIVE_CART_CROSSOVER_CENTS  # exactly $200 → low-value branch (<=)
    assert _passes_price_guard(int(cart * 1.9), cart) is True
    assert _passes_price_guard(int(cart * 1.9) + 1, cart) is False
    above = cart + 1  # $200.01 → substantial branch (70%)
    assert _passes_price_guard(int(above * 0.7), above) is True
    assert _passes_price_guard(int(above * 0.7) + 1, above) is False


def test_zero_or_unknown_cart_has_no_guard():
    assert _passes_price_guard(999999, 0) is True
    assert _passes_price_guard(999999, -5) is True
