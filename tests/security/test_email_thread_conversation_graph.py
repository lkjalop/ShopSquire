import os


def test_thread_reentry_and_sender_drift_combo_routes_security(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_thread_graph_combo.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_thread_graph_combo.db")
    monkeypatch.setenv("THREAD_REENTRY_SILENCE_HOURS", "0")

    import src.app.security.email_security as es

    first = es.evaluate_email_security(
        {
            "message_id": "<tg-1@x>",
            "from_addr": "billing@trustedvendor.com",
            "reply_to": "billing@trustedvendor.com",
            "reply_chain_id": "thread-abc",
            "subject": "Invoice update",
            "body": "standard invoice note",
            "dmarc_fail": False,
        },
        tenant_id="t-thread",
    )
    assert first.get("route") in ("auto_resolve", "human_review", "security_review")

    second = es.evaluate_email_security(
        {
            "message_id": "<tg-2@x>",
            "from_addr": "billing@trvstedvendor.com",
            "reply_to": "billing@trvstedvendor.com",
            "reply_chain_id": "thread-abc",
            "subject": "Re: Invoice update",
            "body": "please process this urgent transfer update",
            "dmarc_fail": False,
        },
        tenant_id="t-thread",
    )
    assert second.get("route") == "security_review"
    assert "thread_reentry_sender_drift_combo" in (second.get("reasons") or [])
    tg = (second.get("evidence_snapshot") or {}).get("thread_graph") or {}
    assert tg.get("reentry_after_silence") is True
    assert tg.get("sender_domain_drift") is True


def test_thread_graph_signals_in_framework_correlation(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_thread_graph_signals.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_thread_graph_signals.db")
    monkeypatch.setenv("THREAD_REENTRY_SILENCE_HOURS", "0")

    import src.app.security.email_security as es

    es.evaluate_email_security(
        {
            "message_id": "<tgs-1@x>",
            "from_addr": "ops@vendor-a.com",
            "reply_to": "ops@vendor-a.com",
            "reply_chain_id": "thread-signals",
            "subject": "PO follow-up",
            "body": "normal follow-up",
            "dmarc_fail": False,
        },
        tenant_id="t-thread-2",
    )
    out = es.evaluate_email_security(
        {
            "message_id": "<tgs-2@x>",
            "from_addr": "ops@vendor-b.com",
            "reply_to": "ops@vendor-b.com",
            "reply_chain_id": "thread-signals",
            "subject": "Re: PO follow-up",
            "body": "please use updated bank route",
            "dmarc_fail": False,
        },
        tenant_id="t-thread-2",
    )
    sa = ((out.get("evidence_snapshot") or {}).get("security_analysis") or {})
    signals = sa.get("signals") or {}
    assert isinstance(signals.get("thread_reentry_after_silence"), bool)
    assert isinstance(signals.get("thread_sender_domain_drift"), bool)
