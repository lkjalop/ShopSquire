from src.app.services.supplier_contact_schedule import decide_contact_schedule


def test_weekend_email_transmits_while_supplier_sla_is_paused():
    result = decide_contact_schedule(
        channel="email",
        expectation={
            "transmission_state": "transmit_now",
            "sla_clock": "paused",
            "next_open_at": "2026-08-10T23:00:00+00:00",
        },
        submitted_at="2026-08-08T01:00:00+00:00",
    )
    assert result.transport_eligible is True
    assert result.queue_state == "pending"
    assert result.not_before == "2026-08-08T01:00:00+00:00"
    assert result.reason == "email_transmits_sla_paused"


def test_phone_only_supplier_remains_a_durable_human_contact_task():
    result = decide_contact_schedule(
        channel="phone",
        expectation={
            "transmission_state": "queue_until_open",
            "sla_clock": "paused",
            "next_open_at": "2026-08-10T23:00:00+00:00",
        },
        submitted_at="2026-08-08T01:00:00+00:00",
    )
    assert result.transport_eligible is False
    assert result.queue_state == "queued_contact"
    assert result.not_before == "2026-08-10T23:00:00+00:00"
