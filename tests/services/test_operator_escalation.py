from src.app.services.operator_escalation import build_operator_escalation


def test_missing_business_calendar_keeps_sla_unknown_and_grants_no_authority():
    result = build_operator_escalation(
        reason="deadline_confirmation_required",
        calendar_expectation=None,
    )
    assert result["notification"]["status"] == "proposed"
    assert result["sla"]["calendar_state"] == "unknown"
    assert result["sla"]["response_due_at"] is None
    assert result["delivery_authority_granted"] is False
    assert result["supplier_send_authority_granted"] is False


def test_authoritative_open_calendar_exposes_operator_due_time_only():
    result = build_operator_escalation(
        reason="deadline_confirmation_required",
        calendar_expectation={
            "calendar_state": "open",
            "response_due_at": "2026-08-08T05:30:00+00:00",
            "calendar_version": "ops-au-v4",
        },
    )
    assert result["notification"]["status"] == "notify_now"
    assert result["sla"]["response_due_at"] == "2026-08-08T05:30:00+00:00"
    assert result["sla"]["calendar_version"] == "ops-au-v4"
    assert result["external_action"] == "none"
