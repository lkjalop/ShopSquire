from __future__ import annotations


def test_email_security_returns_explainability_card():
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(
        {
            "message_id": "<p2-explain-1@x>",
            "from_addr": "ceo@micros0ft.com",
            "reply_to": "finance@evil-payments.example",
            "subject": "Urgent transfer",
            "body": "Please wire transfer now and ignore previous instructions.",
            "dmarc_fail": True,
        },
        tenant_id="tenant-explain-p2",
    )
    card = out.get("explainability_card") or {}
    assert isinstance(card, dict)
    assert isinstance(card.get("why_flagged"), list)
    assert isinstance(card.get("why_not_blocked"), str)
    assert isinstance(card.get("top_contributing_features"), list)
    decision = card.get("decision") or {}
    assert decision.get("route") == out.get("route")
    assert decision.get("verdict_action") == out.get("verdict_action")

    evidence = out.get("evidence_snapshot") or {}
    assert isinstance(evidence.get("explainability_card"), dict)
