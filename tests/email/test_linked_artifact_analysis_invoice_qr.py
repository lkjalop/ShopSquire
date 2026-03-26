from __future__ import annotations


def test_linked_artifact_analysis_uses_invoice_qr_offline_fixture():
    from src.app.security.linked_artifact_analysis import analyze_linked_artifact

    out = analyze_linked_artifact(url="https://ingram-verify-test.com/payment/verify?inv=INV-2026-00847")
    assert out["linked_offline_fixture"] is True
    assert out["linked_offline_fixture_tag"] == "invoice_qr_payment_lure_fixture"
    assert out["linked_artifact_available"] is True
    assert out["linked_artifact_type"] == "html"
    assert out["linked_attack_hypothesis"] == "linked_payment_fraud"
    assert out["linked_policy_action"] == "review"
    assert out["linked_verdict_label"] == "Needs Review"
    assert out["linked_confidence_band"] in {"medium", "high"}
    assert isinstance(out.get("linked_user_summary"), dict)
    assert "what_we_saw" in out["linked_user_summary"]
    assert "payment" in str(out["linked_reason_summary"]).lower()


def test_linked_artifact_analysis_unresolved_url_still_returns_reason_summary():
    from src.app.security.linked_artifact_analysis import analyze_linked_artifact

    out = analyze_linked_artifact(url="https://billing-verify-example.invalid/payment/verify?invoice=12345", timeout=2.0)
    assert out["linked_artifact_available"] is False
    assert out["linked_artifact_type"] == "url_only_unresolved"
    assert out["linked_policy_action"] == "review"
    assert out["linked_verdict_label"] == "Unverified Destination"
    assert out["linked_confidence_band"] in {"low", "medium", "high"}
    assert str(out["linked_reason_summary"]).strip()
