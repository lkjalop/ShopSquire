import os
import json
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_email_detonation_trace.db")
os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_email_detonation_trace.db")


def test_detonation_trace_present(monkeypatch):
    from src.app.security import email_security as es
    from src.app.models.db import db_session
    from sqlalchemy import text

    class DummyDetonator:
        def __call__(self, urls, attachment_hashes):
            return {"provider": "stub", "malicious": True, "score": 0.88, "findings": ["eicar-like"]}

    # Patch detonation to simulate a malicious finding
    monkeypatch.setitem(es.__dict__, "detonate_targets", DummyDetonator())

    out = es.evaluate_email_security(
        {
            "message_id": "<detonate-trace@shopsquire>",
            "from_addr": "alerts@supplier.com",
            "reply_to": "alerts@supplier.com",
            "subject": "Please verify",
            "body": "Visit http://evil.example/login now",
            "attachments": [],
            "external_sender": True,
        },
        tenant_id="t-detonate-trace",
    )
    assert out.get("route") == "security_review"
    dec_id = out.get("decision_id")
    assert dec_id
    # Check a security_scan trace exists with detonation payload included
    with db_session() as db:
        rows = db.execute(text("SELECT payload FROM decision_trace_events WHERE trace_id = :t AND event_type = 'security_scan'"), {"t": dec_id}).fetchall()
    assert rows and len(rows) >= 1
    # Validate payload contains detonation info
    payload = json.loads(rows[0][0])
    det = payload.get("detonation") or {}
    assert det.get("provider") == "stub"
    assert det.get("malicious") is True
