from src.app.deps import redact_for_trace


def test_trace_redaction_preserves_bounded_media_metadata_only():
    redacted = redact_for_trace({
        "image_count": 2,
        "has_image": True,
        "image_untrusted": False,
        "analysis_pending": True,
        "image_data_url": "data:image/png;base64,secret",
        "image_observations": {"ocr_text": "private receipt"},
        "attachment_bytes": "secret",
    })

    assert redacted["image_count"] == 2
    assert redacted["has_image"] is True
    assert redacted["image_untrusted"] is False
    assert redacted["analysis_pending"] is True
    assert redacted["image_data_url"] == "[REDACTED_BLOB]"
    assert redacted["image_observations"] == "[REDACTED_BLOB]"
    assert redacted["attachment_bytes"] == "[REDACTED_BLOB]"


def test_trace_redaction_does_not_allow_media_metadata_strings():
    redacted = redact_for_trace({"image_count": "data:image/png;base64,secret"})
    assert redacted["image_count"] == "[REDACTED_BLOB]"
