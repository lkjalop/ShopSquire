from __future__ import annotations

from src.app.services.policy_gate import PolicyGate


def test_policy_gate_blocks_mass_refund_requests():
    pg = PolicyGate()
    out = pg.evaluate({"request": "Process a refund for all orders this month"})
    assert out.get("verdict") == "block"
    assert out.get("reason") == "bulk_refund_not_allowed"


def test_policy_gate_abac_ip_allowlist_supports_cidr():
    pg = PolicyGate()
    out = pg.evaluate_abac(
        {
            "abac_conditions": {"ip_allowlist": ["10.0.0.0/8", "192.168.0.0/16"]},
            "source_ip": "10.23.4.9",
            "trust_score": 0.9,
        }
    )
    assert out.get("allow") is True


def test_policy_gate_abac_denies_ip_outside_allowlist():
    pg = PolicyGate()
    out = pg.evaluate_abac(
        {
            "abac_conditions": {"ip_allowlist": ["10.0.0.0/8"]},
            "source_ip": "203.0.113.50",
            "trust_score": 0.9,
        }
    )
    assert out.get("allow") is False
    assert "source_ip_not_allowlisted" in (out.get("violations") or [])
