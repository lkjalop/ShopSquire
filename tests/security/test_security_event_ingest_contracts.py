from __future__ import annotations

from src.app.security.security_event_ingest import (
    decide_policy_action,
    normalize_vendor_payload,
)


def test_vendor_mapper_crowdstrike_contract():
    out = normalize_vendor_payload(
        "crowdstrike",
        {
            "detection_id": "det-1",
            "tenant_id": "t1",
            "event_time": "2026-02-26T10:00:00Z",
            "severity": "high",
            "confidence": 0.91,
            "event_type": "network",
            "src_ip": "10.1.1.2",
            "dst_ip": "8.8.8.8",
        },
    )
    assert out["vendor"] == "crowdstrike"
    assert out["event_id"] == "det-1"
    assert out["tenant_id"] == "t1"
    assert out["type"] == "network"
    assert out["severity"] == "high"
    assert float(out["confidence"]) >= 0.9


def test_vendor_mapper_firewall_contract():
    out = normalize_vendor_payload(
        "firewall",
        {
            "log_id": "fw-1",
            "tenant_id": "t2",
            "timestamp": "2026-02-26T11:00:00Z",
            "action": "deny",
            "src_ip": "1.1.1.1",
            "dst_ip": "2.2.2.2",
        },
    )
    assert out["vendor"] == "firewall"
    assert out["event_id"] == "fw-1"
    assert out["type"] == "network"
    assert out["severity"] in ("high", "critical")


def test_vendor_mapper_siem_contract():
    out = normalize_vendor_payload(
        "siem",
        {
            "event_id": "siem-1",
            "type": "prompt-injection",
            "severity": "medium",
            "confidence": 0.6,
            "tenant_id": "t3",
        },
    )
    assert out["vendor"] == "siem"
    assert out["event_id"] == "siem-1"
    assert out["type"] == "prompt-injection"
    assert out["tenant_id"] == "t3"


def test_policy_gate_branches_allow_challenge_escalate_block():
    allow = decide_policy_action({"severity": "low", "confidence": 0.1, "type": "other"})
    challenge = decide_policy_action({"severity": "medium", "confidence": 0.55, "type": "network"})
    escalate = decide_policy_action({"severity": "high", "confidence": 0.7, "type": "phish"})
    block = decide_policy_action({"severity": "critical", "confidence": 0.95, "type": "prompt-injection"})
    assert allow["action"] == "allow"
    assert challenge["action"] == "challenge"
    assert escalate["action"] == "escalate"
    assert block["action"] == "block"
