from src.app.security.payment_threats import evaluate_payment_threat


def test_payment_threat_blocks_suspicious_description():
    out = evaluate_payment_threat(
        provider="paypal",
        uid="u-risk",
        amount_cents=250000,
        currency="USD",
        description="stolen card testing bypass 3ds unauthorized",
        request_ip="10.0.0.12",
        idempotency_key="idem-risk-1",
    )
    assert out["decision"] == "block"
    assert out["requires_escalation"] is True


def test_payment_threat_allows_normal_request():
    out = evaluate_payment_threat(
        provider="paypal",
        uid="u-ok",
        amount_cents=10000,
        currency="USD",
        description="checkout order #123",
        request_ip="10.0.0.13",
        idempotency_key="idem-ok-1",
    )
    assert out["decision"] in ("allow", "review")
    assert out["severity"] in ("info", "high", "critical")

