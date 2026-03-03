from src.app.security.transaction_firewall import evaluate_transaction_firewall


def test_transaction_firewall_step_up_mfa():
    out = evaluate_transaction_firewall(
        provider="stripe",
        uid="u1",
        amount_cents=150000,
        currency="USD",
        description="normal",
        request_ip="1.2.3.4",
        idempotency_key="k1",
        tenant_id="t1",
        trace_id=None,
        device_risk=0.85,
        impossible_travel=True,
        return_abuse_linked=False,
        bin_country_mismatch=False,
    )
    assert out["action"] in {"step_up_mfa", "manual_review", "hard_block"}
    assert "impossible_travel" in (out.get("reasons") or [])

