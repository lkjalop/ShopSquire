from src.app.security.siem_adapter import (
    build_normalized_security_event,
    map_security_event_for_sentinel,
    map_security_event_for_splunk,
)


def _sample_event():
    return build_normalized_security_event(
        source="email_security_agent",
        tenant_id="tenant-a",
        decision_id="dec-1",
        trace_id="trace-1",
        message_id_hash="abc123hash",
        severity="error",
        verdict_action="security_review",
        route="security_review",
        escalation="security_middleware",
        reasons=["auth_alignment_failed", "yara_high_confidence_match"],
        tags=["email_security", "mitre:T1566.002"],
        ioc_counts={"denylisted": 2, "allowlisted": 0},
        risk_band="high",
        playbook_id="pb-sec-001",
        ticket_id="ticket-9",
        evidence={"detonation": {"malicious": True}},
    )


def test_splunk_mapping_contract_shape():
    body = map_security_event_for_splunk(_sample_event())
    assert body["sourcetype"] == "shopsquire:security_handoff"
    evt = body["event"]
    for key in (
        "schema_version",
        "event_time",
        "tenant_id",
        "decision_id",
        "trace_id",
        "message_id_hash",
        "severity",
        "verdict_action",
        "route",
        "escalation",
        "risk_band",
        "reasons",
        "tags",
        "ioc",
        "contract_version",
    ):
        assert key in evt
    assert evt["contract_version"] == "splunk.v1"


def test_sentinel_mapping_contract_shape():
    body = map_security_event_for_sentinel(_sample_event())
    for key in (
        "TimeGenerated",
        "TenantId_s",
        "EventVendor_s",
        "EventProduct_s",
        "EventSchemaVersion_s",
        "EventTime_t",
        "DecisionId_s",
        "TraceId_s",
        "MessageIdHash_s",
        "Severity_s",
        "VerdictAction_s",
        "Route_s",
        "Escalation_s",
        "RiskBand_s",
        "Reasons_s",
        "Tags_s",
        "Ioc_s",
        "Evidence_s",
        "ContractVersion_s",
    ):
        assert key in body
    assert body["ContractVersion_s"] == "sentinel.v1"
