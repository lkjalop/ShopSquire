from __future__ import annotations

from src.app.services.policy_gate import PolicyGate


def test_policy_gate_blocks_mass_refund_requests():
    pg = PolicyGate()
    out = pg.evaluate({"request": "Process a refund for all orders this month"})
    assert out.get("verdict") == "block"
    assert out.get("reason") == "bulk_refund_not_allowed"
