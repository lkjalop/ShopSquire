import os
import pytest

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")


def _payload(spf: str, dkim: str, dmarc: str, policy: str):
    return {
        "message_id": "<align-case@shopsquire>",
        "from_addr": "alerts@supplier.com",
        "reply_to": "alerts@supplier.com",
        "subject": "Alignment check",
        "body": "Alignment scenario",
        "attachments": [],
        "spf_result": spf,
        "dkim_result": dkim,
        "dmarc_result": dmarc,
        "dmarc_policy": policy,
        "external_sender": True,
    }


@pytest.mark.parametrize(
    "spf,dkim,dmarc,policy,expect_route",
    [
        ("pass", "fail", "fail", "reject", "security_review"),
        ("pass", "fail", "quarantine", "p=reject", "security_review"),
        ("fail", "pass", "fail", "quarantine", "security_review"),
        # Even with perfect auth, external sender + lack of trust context can still require review.
        ("pass", "pass", "pass", "none", "human_review"),
    ],
)
def test_dmarc_misalignment_forces_security_review(spf, dkim, dmarc, policy, expect_route):
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(_payload(spf, dkim, dmarc, policy), tenant_id="t-align")
    assert out.get("route") == expect_route
    ev = out.get("evidence_snapshot") or {}
    assert (ev.get("auth_verdicts") or {}).get("dmarc_result") == dmarc
    assert (ev.get("auth_verdicts") or {}).get("dmarc_policy") == policy
