import os

from fastapi.testclient import TestClient


def _app():
    from src.app.main import create_app

    return create_app()


def test_siem_handoff_emitted_for_security_review(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_siem.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_siem.db")

    import src.app.security.email_security as es

    sent = {"count": 0}

    def _fake_emit(event):
        sent["count"] += 1
        return {"sent": ["splunk_hec"], "failed": []}

    monkeypatch.setattr(es, "emit_security_handoff", _fake_emit)

    out = es.evaluate_email_security(
        {
            "message_id": "<siem@x>",
            "from_addr": "ceo@micros0ft.com",
            "reply_to": "finance@evil-payments.example",
            "subject": "Urgent wire transfer",
            "body": "Please wire now to https://evil-payments.example/pay",
            "dmarc_fail": True,
            "spf_result": "fail",
            "dkim_result": "fail",
            "dmarc_policy": "reject",
        },
        tenant_id="t-siem",
    )
    assert out["route"] == "security_review"
    assert sent["count"] == 1
    assert isinstance(out.get("siem_handoff"), dict)


def test_email_security_simulation_endpoint(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_simulate.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_simulate.db")
    client = TestClient(_app())

    r = client.post(
        "/api/v1/email_security/simulate",
        params={"scenario": "supplier_bank_change"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    result = body.get("result") or {}
    assert result.get("route") in ("human_review", "security_review")
    assert "oob_verification_required" in (result.get("reasons") or [])


def test_demo_funnel_endpoint(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_funnel.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_funnel.db")
    client = TestClient(_app())

    # Seed one incident through simulation path.
    r1 = client.post(
        "/api/v1/email_security/simulate",
        params={"scenario": "bec"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r1.status_code == 200

    r2 = client.get("/api/v1/admin/email_security/demo/funnel", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    body = r2.json()
    funnel = body.get("funnel") or {}
    assert "detected" in funnel
    assert "security_review" in funnel
    assert isinstance(body.get("latest"), list)


def test_llm_assist_non_authoritative(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_llm_assist.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_llm_assist.db")
    import src.app.security.email_security as es

    monkeypatch.setattr(es, "load_feature_flags", lambda *_a, **_k: {"EMAIL_LLM_ASSIST_ENABLED": True, "SECURITY_THRESHOLDS": {}})
    out = es.evaluate_email_security(
        {
            "message_id": "<assist@x>",
            "from_addr": "hello@supplier.com",
            "reply_to": "hello@supplier.com",
            "subject": "General inquiry",
            "body": "Need status update for standard order.",
            "dmarc_fail": False,
        },
        tenant_id="t-assist",
    )
    assert out.get("llm_assist", {}).get("non_authoritative") is True
    assert out.get("route") in ("auto_resolve", "human_review", "security_review")


def test_enrichment_and_detonation_can_escalate(monkeypatch):
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_enrich_det.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_enrich_det.db")
    import src.app.security.email_security as es

    monkeypatch.setattr(es, "enrich_iocs", lambda _iocs: {"items": [{"malicious": True}], "malicious_hits": 1})
    monkeypatch.setattr(es, "detonate_targets", lambda _u, _h: {"provider": "test", "malicious": True, "score": 0.9, "findings": []})
    out = es.evaluate_email_security(
        {
            "message_id": "<enr@x>",
            "from_addr": "alerts@supplier.com",
            "reply_to": "alerts@supplier.com",
            "subject": "Check this link",
            "body": "Visit https://example.com/login",
            "dmarc_fail": False,
        },
        tenant_id="t-enrich",
    )
    assert out.get("route") == "security_review"
    assert out.get("detonation", {}).get("malicious") is True
    assert int((out.get("enrichment") or {}).get("malicious_hits") or 0) >= 1


def test_email_security_extended_simulation_scenarios():
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_simulate_extended.db")
    os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_simulate_extended.db")
    client = TestClient(_app())

    for scenario in ("ioc_phish", "supplier_reply_hijack"):
        r = client.post(
            "/api/v1/email_security/simulate",
            params={"scenario": scenario},
            headers={"x-api-key": "local-owner-key"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"
        result = body.get("result") or {}
        assert result.get("route") in ("human_review", "security_review", "auto_resolve")
