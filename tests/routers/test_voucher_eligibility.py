"""Security PR B1/B2 — voucher eligibility enforcement (min_order_cents, applies_to_skus).

These columns were SELECTed but never enforced: a $50-off "$500-min" voucher applied to a $1
cart, and a SKU-restricted voucher applied to anything. The eligibility gate is a pure function
(`_voucher_eligibility_error`) wired into `_apply_voucher_atomic` before the cart binding —
tested here directly so it's deterministic and DB-free.
"""
from __future__ import annotations

from src.app.routers.cart import _parse_applies_to_skus, _voucher_eligibility_error


# ── applies_to_skus parser ────────────────────────────────────────────────────
def test_parse_applies_to_skus_json():
    assert _parse_applies_to_skus('["SKU-1","sku-2"]') == {"SKU-1", "SKU-2"}


def test_parse_applies_to_skus_csv_and_spaces():
    assert _parse_applies_to_skus("SKU-1, sku-2  SKU-3") == {"SKU-1", "SKU-2", "SKU-3"}


def test_parse_applies_to_skus_empty_means_no_restriction():
    assert _parse_applies_to_skus(None) == set()
    assert _parse_applies_to_skus("") == set()
    assert _parse_applies_to_skus("   ") == set()


# ── B1: min_order_cents ───────────────────────────────────────────────────────
def test_min_order_not_met_is_rejected():
    # $500-min voucher on a $10 cart → rejected.
    assert _voucher_eligibility_error(50000, None, 1000, None) == "voucher_min_order_not_met"


def test_min_order_met_passes():
    assert _voucher_eligibility_error(50000, None, 60000, None) is None


def test_no_min_order_is_unrestricted():
    assert _voucher_eligibility_error(0, None, 1, None) is None
    assert _voucher_eligibility_error(None, None, 1, None) is None


# ── B2: applies_to_skus ───────────────────────────────────────────────────────
def test_applies_to_skus_mismatch_is_rejected():
    assert _voucher_eligibility_error(0, '["SKU-CLEARANCE"]', 10000, ["SKU-OTHER"]) == \
        "voucher_not_applicable_to_cart"


def test_applies_to_skus_match_passes_case_insensitive():
    assert _voucher_eligibility_error(0, '["SKU-CLEARANCE","SKU-X"]', 10000, ["sku-x"]) is None


def test_applies_to_skus_empty_applies_to_all():
    assert _voucher_eligibility_error(0, None, 10000, ["ANYTHING"]) is None


def test_both_gates_min_order_checked_first():
    # Below min AND wrong SKU → min_order is the reported reason (checked first).
    assert _voucher_eligibility_error(50000, '["SKU-X"]', 1000, ["SKU-OTHER"]) == \
        "voucher_min_order_not_met"
