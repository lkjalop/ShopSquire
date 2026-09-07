from src.app.deps import security_sanitize, redact_for_trace


def test_canonical_case_uuid_survives_both_privacy_passes():
    case_id = "sc-48504246-2713-44b7-9a2c-5de1cabe3977"
    result = redact_for_trace(security_sanitize({"case_id": case_id}))
    assert result["case_id"] == case_id


def test_an_id_field_does_not_exempt_phone_numbers_from_redaction():
    payload = {"case_id": "+61 412 345 678", "message": "Call +61 412 345 678"}
    result = redact_for_trace(security_sanitize(payload))
    assert "412" not in result["case_id"]
    assert "412" not in result["message"]
