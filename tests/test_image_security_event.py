"""Security_Observer ingests CV adversarial signals (C1).

A flagged image (steg / QR-injection / OCR-injection / manipulation / adversarial) must enter the
SECURITY-EVENT stream, not just the decision trace — otherwise the platform's headline image-fraud
detection is cosmetic (a UI badge) instead of a correlated, alertable security event.
"""
from __future__ import annotations

from src.app.routers.recommend import _image_security_event

_FW = {
    "mitre_atlas": ["AML.T0051"],
    "owasp_llm_top10": ["LLM01"],
    "stride_categories": ["Tampering"],
    "dread": {"score": 7},
    "cvss": {"score": 8.1},
}
_SIGNALS = {
    "qr_prompt_injection": True,
    "steg_suspicious": True,
    "manipulation_detected": False,
}


def test_clean_image_emits_no_event():
    assert _image_security_event(
        sec_signals={"qr_code_detected": False}, frameworks=_FW, severity="info",
        policy_route="allow", uid="u1", query="laptop", trace_id="t1",
    ) is None


def test_lockdown_route_builds_block_verdict_event_with_cv_signals():
    evt = _image_security_event(
        sec_signals=_SIGNALS, frameworks=_FW, severity="high",
        policy_route="lockdown", uid="u1", query="gaming laptop", trace_id="t-9",
    )
    assert evt is not None
    assert evt["analysis"]["verdict"] == "block"
    assert evt["analysis"]["severity"] == "high"
    # cv_signals are present at the top level so observer.compute_risk can factor them.
    assert evt["payload"]["cv_signals"]["qr_prompt_injection"] is True
    # Only truthy signals become active flags.
    assert evt["analysis"]["signals"] == {"qr_prompt_injection": True, "steg_suspicious": True}
    assert evt["analysis"]["mitre_atlas"] == ["AML.T0051"]
    assert evt["payload"]["event_ref"] == "image_security:t-9"


def test_escalate_and_sanitize_verdicts():
    assert _image_security_event(sec_signals=_SIGNALS, frameworks={}, severity="high",
                                 policy_route="escalate", uid="u", query="q", trace_id="t")["analysis"]["verdict"] == "escalate"
    assert _image_security_event(sec_signals=_SIGNALS, frameworks={}, severity="warn",
                                 policy_route="visual_sanitized", uid="u", query="q", trace_id="t")["analysis"]["verdict"] == "sanitize"


def test_query_is_pii_scrubbed_in_event():
    evt = _image_security_event(
        sec_signals=_SIGNALS, frameworks={}, severity="high", policy_route="lockdown",
        uid="u", query="email me at john@example.com", trace_id="t",
    )
    assert "john@example.com" not in evt["payload"]["query"]
    assert "[REDACTED_EMAIL]" in evt["payload"]["query"]
