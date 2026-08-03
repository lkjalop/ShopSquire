import pytest

from src.app.services.procurement_payment_consequences import evaluate_payment_consequence


def test_unknown_supply_allows_authorization_but_prevents_full_capture():
    result = evaluate_payment_consequence(
        plan_type="full_payment", total_amount_cents=359_920_00, currency="AUD",
        promise_feasibility="unknown", policy_version="payment-v1",
        authorization_expires_at="2026-08-10T00:00:00+00:00",
        evaluated_at="2026-08-08T00:00:00+00:00",
    )
    assert result["status"] == "authorization_only"
    assert result["state_prevented"] == "full_payment_capture"


def test_deposit_keeps_balance_blocked_until_supplier_confirmation():
    result = evaluate_payment_consequence(
        plan_type="deposit", total_amount_cents=100_000, currency="AUD",
        promise_feasibility="unknown", deposit_bps=2000, policy_version="payment-v1",
    )
    assert result["deposit_amount_cents"] == 20_000
    assert result["balance_amount_cents"] == 80_000
    assert result["state_prevented"] == "balance_capture"


@pytest.mark.parametrize("days", [7, 15, 30, 45, 60, 90])
def test_only_authoritatively_approved_b2b_terms_create_a_receivable(days):
    blocked = evaluate_payment_consequence(
        plan_type="b2b_terms", total_amount_cents=100_000, currency="AUD",
        promise_feasibility="met", b2b_terms_days=days, account_terms_approved=False,
        policy_version="payment-v1",
    )
    assert blocked["status"] == "terms_not_approved"
    approved = evaluate_payment_consequence(
        plan_type="b2b_terms", total_amount_cents=100_000, currency="AUD",
        promise_feasibility="met", b2b_terms_days=days, account_terms_approved=True,
        policy_version="payment-v1",
    )
    assert approved["status"] == "terms_approved" and approved["terms_days"] == days


def test_expired_authorization_prevents_capture():
    result = evaluate_payment_consequence(
        plan_type="full_payment", total_amount_cents=100_000, currency="AUD",
        promise_feasibility="met", policy_version="payment-v1",
        authorization_expires_at="2026-08-07T00:00:00+00:00",
        evaluated_at="2026-08-08T00:00:00+00:00",
    )
    assert result["status"] == "authorization_expired"
    assert result["state_prevented"] == "payment_capture"
