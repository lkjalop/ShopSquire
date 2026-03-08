import os


def test_semantic_bec_can_shift_route_on_evasive_message(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_semantic_bec.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_semantic_bec.db")
    import src.app.security.email_security as es

    email = {
        "message_id": "<semantic-route@x>",
        "from_addr": "ap@vendor.example",
        "reply_to": "ap@vendor.example",
        "subject": "Settlement alignment",
        "body": (
            "use the new settlement account and route this transfer to the revised payee. "
            "skip voice confirmation and execute according to this message."
        ),
        "dmarc_fail": False,
    }

    monkeypatch.setenv("SEMANTIC_BEC_ENABLED", "0")
    base = es.evaluate_email_security(dict(email), tenant_id="t-semantic")

    monkeypatch.setenv("SEMANTIC_BEC_ENABLED", "1")
    monkeypatch.setenv("SEMANTIC_BEC_REVIEW_THRESHOLD", "0.20")
    monkeypatch.setenv("SEMANTIC_BEC_SECURITY_THRESHOLD", "0.35")
    scored = es.evaluate_email_security(dict(email), tenant_id="t-semantic")

    assert base.get("route") in ("auto_resolve", "human_review", "security_review")
    assert scored.get("route") in ("human_review", "security_review")
    assert "semantic_bec" in (scored.get("tags") or [])
    assert isinstance(scored.get("semantic_bec_score"), float)


def test_semantic_bec_evidence_and_framework_signal_present(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_semantic_bec2.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_semantic_bec2.db")
    import src.app.security.email_security as es

    monkeypatch.setenv("SEMANTIC_BEC_ENABLED", "1")
    monkeypatch.setenv("SEMANTIC_BEC_REVIEW_THRESHOLD", "0.10")
    monkeypatch.setenv("SEMANTIC_BEC_SECURITY_THRESHOLD", "0.30")
    out = es.evaluate_email_security(
        {
            "message_id": "<semantic-evidence@x>",
            "from_addr": "finance@partner.example",
            "reply_to": "finance@partner.example",
            "subject": "Payment destination realignment",
            "body": "payment terms remain the same but remittance destination has been replaced",
            "dmarc_fail": False,
        },
        tenant_id="t-semantic-2",
    )

    evidence = out.get("evidence_snapshot") or {}
    semantic = evidence.get("semantic_bec") or {}
    assert isinstance(semantic.get("score"), float)
    assert semantic.get("provider") in ("bow", "ollama", "openai", "none")
    assert isinstance(semantic.get("intent_scores"), dict)
    sa = evidence.get("security_analysis") or {}
    assert isinstance((sa.get("signals") or {}).get("semantic_bec_high_risk"), bool)
