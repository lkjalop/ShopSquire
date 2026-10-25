from src.app.deps import security_sanitize, redact_for_trace
import pytest


def test_canonical_case_uuid_survives_both_privacy_passes():
    case_id = "sc-48504246-2713-44b7-9a2c-5de1cabe3977"
    result = redact_for_trace(security_sanitize({"case_id": case_id}))
    assert result["case_id"] == case_id


def test_an_id_field_does_not_exempt_phone_numbers_from_redaction():
    payload = {"case_id": "+61 412 345 678", "message": "Call +61 412 345 678"}
    result = redact_for_trace(security_sanitize(payload))
    assert "412" not in result["case_id"]
    assert "412" not in result["message"]


def test_minted_ticket_uuid_remains_joinable_in_the_audit():
    ticket_id = "TKT-971da561-5251-4175-9473-10c33df3cef6"
    result = redact_for_trace(security_sanitize({"ticket_id": ticket_id}))
    assert result["ticket_id"] == ticket_id


@pytest.mark.parametrize("value", ["+61 412 345 678", "buyer@example.test", "123-45-6789"])
def test_ticket_field_does_not_exempt_arbitrary_pii(value):
    result = redact_for_trace(security_sanitize({"ticket_id": value}))
    assert result["ticket_id"] != value


def test_ticket_uuid_with_appended_pii_is_not_exempt():
    value = "TKT-971da561-5251-4175-9473-10c33df3cef6 buyer@example.test"
    result = redact_for_trace(security_sanitize({"ticket_id": value}))
    assert "buyer@example.test" not in result["ticket_id"]
