"""The vision triage must NOT echo raw PII (SSN/PAN) the linked-artifact scan extracted — masking
keeps the detection signal (count/type) while dropping cleartext from the response/logs/event."""
from __future__ import annotations

from src.app.routers.vision import _redact_linked_artifact_pii, _mask_ssn


def test_mask_ssn_keeps_last4():
    assert _mask_ssn("205-52-0027") == "***-**-0027"
    assert _mask_ssn("421371396") == "***-**-1396"
    assert _mask_ssn("12") == "***-**-****"


def test_redact_masks_ssn_hits_preserves_count_and_metadata():
    linked = {
        "ssn_hits": ["205-52-0027", "421-37-1396"],
        "url": "http://x.invalid/p",
        "country": "AU",
        "linked_reason_summary": "exposes SSN",
    }
    out = _redact_linked_artifact_pii(linked)
    assert out["ssn_hits"] == ["***-**-0027", "***-**-1396"]
    assert len(out["ssn_hits"]) == 2                 # count still derivable
    assert "205-52-0027" not in str(out)             # no cleartext anywhere
    assert out["url"] == "http://x.invalid/p"        # non-PII metadata untouched
    assert out["country"] == "AU"
    assert out["linked_reason_summary"] == "exposes SSN"


def test_redact_masks_card_hits():
    out = _redact_linked_artifact_pii({"card_hits": ["5481 1234 0987 4121"]})
    assert out["card_hits"] == ["****-****-****-4121"]
    assert "5481" not in str(out)


def test_redact_idempotent_and_safe_on_empty():
    assert _redact_linked_artifact_pii({}) == {}
    assert _redact_linked_artifact_pii(None) is None
    once = _redact_linked_artifact_pii({"ssn_hits": ["205-52-0027"]})
    twice = _redact_linked_artifact_pii(dict(once))
    assert twice["ssn_hits"] == once["ssn_hits"]     # masking a mask stays masked
