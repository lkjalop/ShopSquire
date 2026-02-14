import os
import json
import pytest
from sqlalchemy import text

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_security.db")
os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_security.db")


def _base_email(**overrides):
    e = {
        "provider": "imap",
        "from_addr": "bob@internal.example.com",
        "reply_to": "bob@internal.example.com",
        "subject": "Test",
        "body": "hello",
        "message_id": "mid-1",
        "spf": {"result": "pass"},
        "dkim": {"result": "pass"},
        "dmarc": {"result": "pass"},
        "attachments": [],
    }
    e.update(overrides)
    return e


def test_internal_trusted_auth_pass_auto_resolve(monkeypatch):
    from src.app.security import email_security as es
    # Trusted internal with all auth passing should remain auto_resolve unless critical
    email = _base_email(
        from_addr="ceo@corp.example.com",
        reply_to="ceo@corp.example.com",
    )
    res = es.evaluate_email_security(email)
    assert res.get("route") in ("auto_resolve", "human_review")
    # No critical indicators provided; should not be security_review
    assert res.get("route") != "security_review"


def test_external_misaligned_forces_security_review(monkeypatch):
    from src.app.security import email_security as es
    email = _base_email(
        from_addr="attacker@evil.example.com",
        reply_to="ceo@corp.example.com",
        dmarc={"result": "fail"},
    )
    res = es.evaluate_email_security(email)
    assert res.get("route") == "security_review"


def test_detonation_malicious_updates_route_and_trace(monkeypatch):
    from src.app.security import email_security as es
    # Monkeypatch detonate_targets to return malicious True
    def _fake_detonate(urls, hashes):
        return {"provider": "test_sandbox", "malicious": True, "score": 0.95, "findings": [{"type": "url", "risk": "high"}]}

    monkeypatch.setattr(es, "detonate_targets", _fake_detonate)
    email = _base_email(
        from_addr="vendor@partner.example.org",
        reply_to="vendor@partner.example.org",
        body="Check this: https://example.com/bad",
        message_id="mid-2",
    )
    res = es.evaluate_email_security(email)
    assert res.get("route") == "security_review"
    dec_id = res.get("decision_id")
    assert dec_id
    # Verify a security_scan trace contains detonation.malicious true
    from src.app.models.db import db_session
    with db_session() as db:
        row = db.execute(
            text("SELECT payload FROM decision_trace_events WHERE trace_id = :t AND event_type = 'security_scan' ORDER BY created_at DESC LIMIT 1"),
            {"t": dec_id},
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        det = (payload or {}).get("detonation") or {}
        assert det.get("malicious") is True
