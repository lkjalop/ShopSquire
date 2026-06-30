"""Unit tests for src.app.services.price_conversion — drop-in replacement contract."""

from __future__ import annotations

import pytest

from src.app.services.price_conversion import cents_to_dollars, dollars_to_cents


class TestCentsToDollars:
    def test_basic_conversion(self):
        assert cents_to_dollars(12345) == 123.45

    def test_zero(self):
        assert cents_to_dollars(0) == 0.0

    def test_none_returns_zero(self):
        assert cents_to_dollars(None) == 0.0

    def test_string_numeric(self):
        assert cents_to_dollars("12345") == 123.45

    def test_non_numeric_returns_zero(self):
        assert cents_to_dollars("not a number") == 0.0

    def test_rounded_to_2dp(self):
        # 100.005 cents → 1.00005 → round 2dp → 1.0
        assert cents_to_dollars(100, ndigits=2) == 1.0

    def test_no_round_preserves_float(self):
        # Matches the legacy `price_cents / 100.0` idiom — no implicit rounding
        result = cents_to_dollars(33)
        assert result == 0.33

    def test_negative(self):
        assert cents_to_dollars(-500) == -5.0

    def test_float_cents_input(self):
        # Some legacy sites passed `float(...)` already — must not lose info
        assert cents_to_dollars(150000.0) == 1500.0


class TestDollarsToCents:
    def test_basic_conversion(self):
        assert dollars_to_cents(123.45) == 12345

    def test_zero(self):
        assert dollars_to_cents(0) == 0

    def test_none_returns_zero(self):
        assert dollars_to_cents(None) == 0

    def test_string_numeric(self):
        assert dollars_to_cents("99.99") == 9999

    def test_non_numeric_returns_zero(self):
        assert dollars_to_cents("nope") == 0

    def test_rounding_half_up(self):
        # 1.005 * 100 = 100.49999... in float → round → 100 (banker's rounding)
        # Critical: we are NOT promising banker's vs half-up; we promise the
        # legacy behaviour `int(round(d * 100.0))`. Pin that.
        assert dollars_to_cents(1.005) == int(round(1.005 * 100.0))

    def test_integer_input(self):
        assert dollars_to_cents(50) == 5000


class TestRoundTrip:
    @pytest.mark.parametrize("cents", [0, 1, 99, 100, 12345, 999999])
    def test_cents_dollars_cents_is_identity(self, cents):
        assert dollars_to_cents(cents_to_dollars(cents)) == cents
