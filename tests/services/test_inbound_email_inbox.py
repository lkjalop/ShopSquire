import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.inbound_email_inbox import ingest_email


_DDL = """
CREATE TABLE inbound_email_inbox (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_message_id VARCHAR(512) NOT NULL,
    subscription_id VARCHAR(512),
    fulfillment_case_id VARCHAR(64),
    status VARCHAR(64) NOT NULL,
    security_route VARCHAR(64),
    sanitized_payload_json TEXT NOT NULL,
    security_verdict_json TEXT,
    raw_evidence_ref VARCHAR(255) NOT NULL,
    received_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE (tenant_id, provider, provider_message_id)
)
"""

_EVIDENCE_DDL = """
CREATE TABLE inbound_email_raw_evidence (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_message_id VARCHAR(512) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    cipher VARCHAR(32) NOT NULL,
    encryption_key_id VARCHAR(64) NOT NULL,
    nonce_b64 VARCHAR(64) NOT NULL,
    ciphertext_b64 TEXT NOT NULL,
    retention_until TIMESTAMP NOT NULL,
    legal_hold BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (tenant_id, provider, provider_message_id)
)
"""

_CORRELATION_DDL = """
CREATE TABLE outbound_email_correlation (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_message_id VARCHAR(512) NOT NULL,
    provider_thread_id VARCHAR(512),
    fulfillment_case_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (tenant_id, provider, provider_message_id)
)
"""

_DISPOSITION_DDL = """
CREATE TABLE inbound_email_quarantine_disposition (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    inbox_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    actor_id VARCHAR(255) NOT NULL,
    note TEXT,
    fresh_case_id VARCHAR(64),
    created_at TIMESTAMP NOT NULL,
    UNIQUE (tenant_id, inbox_id)
)
"""

_AUDIT_DDL = """
CREATE TABLE email_evidence_operation_audit (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    evidence_id VARCHAR(64),
    inbox_id VARCHAR(64),
    action VARCHAR(64) NOT NULL,
    actor_id VARCHAR(255) NOT NULL,
    purpose TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP NOT NULL
)
"""


@pytest.fixture(autouse=True)
def evidence_key(monkeypatch):
    monkeypatch.setenv("EMAIL_EVIDENCE_ENCRYPTION_KEY", "11" * 32)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text(_DDL))
        conn.execute(text(_EVIDENCE_DDL))
        conn.execute(text(_CORRELATION_DDL))
        conn.execute(text(_DISPOSITION_DDL))
        conn.execute(text(_AUDIT_DDL))
    return Session(engine)


def test_inbox_is_idempotent_and_does_not_store_raw_attachment():
    db = _db()
    email = {
        "message_id": "<provider-1>",
        "from_addr": "person@example.test",
        "subject": "Quote",
        "body": "Call 0412 345 678 about the quote.",
        "attachments": [
            {
                "name": "quote.pdf",
                "content_type": "application/pdf",
                "content_b64": "sensitive-raw-content",
            }
        ],
    }
    evaluator = lambda _email, tenant_id=None: {"route": "security_review", "severity": "error"}

    first = ingest_email(
        db,
        provider="gmail",
        tenant_id="tenant-a",
        subscription_id="sub-a",
        email=email,
        security_evaluator=evaluator,
    )
    db.commit()
    second = ingest_email(
        db,
        provider="gmail",
        tenant_id="tenant-a",
        subscription_id="sub-a",
        email=email,
        security_evaluator=evaluator,
    )

    assert first["duplicate"] is False
    assert first["status"] == "quarantined"
    assert second["duplicate"] is True
    row = db.execute(
        text(
            "SELECT sanitized_payload_json, raw_evidence_ref "
            "FROM inbound_email_inbox WHERE tenant_id='tenant-a'"
        )
    ).fetchone()
    payload = json.loads(row[0])
    assert "content_b64" not in payload["attachments"][0]
    assert "sensitive-raw-content" not in row[0]
    assert row[1].startswith("evidence:")
    evidence = db.execute(
        text(
            "SELECT cipher, ciphertext_b64, retention_until "
            "FROM inbound_email_raw_evidence WHERE tenant_id='tenant-a'"
        )
    ).fetchone()
    assert evidence[0] == "AES-256-GCM"
    assert "sensitive-raw-content" not in evidence[1]
    assert evidence[2] is not None
    assert db.execute(text("SELECT COUNT(*) FROM inbound_email_raw_evidence")).scalar_one() == 1


def test_same_provider_message_id_is_isolated_by_tenant():
    db = _db()
    email = {"message_id": "same", "from_addr": "supplier@example.test", "attachments": []}
    evaluator = lambda _email, tenant_id=None: {"route": "auto_resolve", "severity": "info"}
    a = ingest_email(db, provider="m365", tenant_id="a", email=email, security_evaluator=evaluator)
    db.commit()
    b = ingest_email(db, provider="m365", tenant_id="b", email=email, security_evaluator=evaluator)
    db.commit()
    assert a["duplicate"] is False
    assert b["duplicate"] is False
    assert db.execute(text("SELECT COUNT(*) FROM inbound_email_inbox")).scalar_one() == 2


def test_payload_selected_case_is_not_authoritative():
    db = _db()
    selected = "11111111-1111-4111-8111-111111111111"
    email = {
        "message_id": "attempt-1",
        "fulfillment_case_id": selected,
        "from_addr": "supplier@example.test",
        "subject": "Unrelated invoice",
        "attachments": [],
    }
    result = ingest_email(
        db,
        provider="gmail",
        tenant_id="tenant-a",
        email=email,
        fulfillment_case_id=selected,
        security_evaluator=lambda *_args, **_kwargs: {"route": "auto_resolve"},
    )
    assert result["status"] == "evaluated"
    assert result["fulfillment_case_id"] is None


def test_raw_evidence_fails_closed_without_encryption_key(monkeypatch):
    monkeypatch.delenv("EMAIL_EVIDENCE_ENCRYPTION_KEY", raising=False)
    db = _db()
    with pytest.raises(RuntimeError, match="email_evidence_encryption_key_required"):
        ingest_email(
            db,
            provider="gmail",
            tenant_id="tenant-a",
            email={
                "message_id": "no-key",
                "from_addr": "supplier@example.test",
                "attachments": [],
            },
            security_evaluator=lambda *_args, **_kwargs: {"route": "auto_resolve"},
        )
    assert db.execute(text("SELECT COUNT(*) FROM inbound_email_inbox")).scalar_one() == 0
    assert db.execute(text("SELECT COUNT(*) FROM inbound_email_raw_evidence")).scalar_one() == 0


def test_retention_purge_respects_legal_hold():
    from datetime import datetime, timezone
    from src.app.services.inbound_email_evidence import purge_expired_evidence

    db = _db()
    for message in ("expired-delete", "expired-hold"):
        ingest_email(
            db,
            provider="gmail",
            tenant_id="tenant-a",
            email={"message_id": message, "from_addr": "supplier@example.test", "attachments": []},
            security_evaluator=lambda *_args, **_kwargs: {"route": "auto_resolve"},
        )
    db.execute(
        text(
            "UPDATE inbound_email_raw_evidence SET retention_until='2000-01-01', "
            "legal_hold=CASE WHEN provider_message_id='expired-hold' THEN 1 ELSE 0 END"
        )
    )
    assert purge_expired_evidence(
        db,
        actor_id="retention-worker",
        purpose="scheduled retention",
        now=datetime.now(timezone.utc),
    ) == 1
    remaining = db.execute(
        text("SELECT provider_message_id FROM inbound_email_raw_evidence")
    ).scalar_one()
    assert remaining == "expired-hold"


def test_non_uuid_reply_correlates_through_durable_provider_reference(monkeypatch):
    from src.app.services.email_thread_correlation import record_outbound_reference
    import src.app.services.fulfillment.external_comms as external_comms

    db = _db()
    record_outbound_reference(
        db,
        tenant_id="tenant-a",
        provider="supplier_transport",
        provider_message_id="<outbound-provider-42@example>",
        case_id="case-non-uuid-42",
    )
    seen = {}

    def fake_receive(_db, **kwargs):
        seen.update(kwargs)
        return type("Result", (), {"state": "QUOTE_RECEIVED"})()

    monkeypatch.setattr(external_comms, "receive_email_reply", fake_receive)
    result = ingest_email(
        db,
        provider="gmail",
        tenant_id="tenant-a",
        email={
            "message_id": "<inbound-provider-43@example>",
            "in_reply_to": "<outbound-provider-42@example>",
            "from_addr": "supplier@example.test",
            "subject": "Re: quote",
            "attachments": [],
        },
        security_evaluator=lambda *_args, **_kwargs: {"route": "auto_resolve"},
    )
    assert result["fulfillment_case_id"] == "case-non-uuid-42"
    assert seen["case_id"] == "case-non-uuid-42"


def test_quarantine_disposition_is_audited_and_never_releases_content():
    from src.app.services.inbound_quarantine_dispositions import record_disposition

    db = _db()
    result = ingest_email(
        db,
        provider="gmail",
        tenant_id="tenant-a",
        email={"message_id": "unsafe-1", "from_addr": "supplier@example.test", "attachments": []},
        security_evaluator=lambda *_args, **_kwargs: {"route": "security_review"},
    )
    disposition = record_disposition(
        db,
        tenant_id="tenant-a",
        inbox_id=result["inbox_id"],
        action="discard",
        actor_id="operator-1",
        note="Confirmed malicious out of band",
    )
    assert disposition["action"] == "discard"
    row = db.execute(
        text("SELECT status, security_route FROM inbound_email_inbox WHERE id=:id"),
        {"id": result["inbox_id"]},
    ).fetchone()
    assert row == ("disposed_discard", "security_review")
    audit = db.execute(
        text(
            "SELECT action, actor_id, note FROM inbound_email_quarantine_disposition "
            "WHERE inbox_id=:id"
        ),
        {"id": result["inbox_id"]},
    ).fetchone()
    assert audit == ("discard", "operator-1", "Confirmed malicious out of band")


def test_attachment_cannot_race_deep_enrichment_into_quote_state(monkeypatch):
    import src.app.security.email_security as security

    monkeypatch.setattr(
        security,
        "evaluate_email_security",
        lambda *_args, **_kwargs: {
            "route": "auto_resolve",
            "severity": "info",
            "reasons": [],
        },
    )
    db = _db()
    result = ingest_email(
        db,
        provider="gmail",
        tenant_id="tenant-a",
        email={
            "message_id": "attachment-pending",
            "from_addr": "supplier@example.test",
            "subject": "Quote attached",
            "attachments": [{"name": "quote.pdf", "content_b64": "AA=="}],
        },
    )
    assert result["status"] == "quarantined"
    assert result["security_route"] == "security_review"
    verdict = json.loads(
        db.execute(
            text("SELECT security_verdict_json FROM inbound_email_inbox WHERE id=:id"),
            {"id": result["inbox_id"]},
        ).scalar_one()
    )
    assert "deep_enrichment_pending" in verdict["reasons"]


def test_evidence_read_hold_and_dual_key_rotation_are_audited(monkeypatch):
    from src.app.services.inbound_email_evidence import (
        load_raw_evidence,
        rotate_evidence_keys,
        set_legal_hold,
    )

    db = _db()
    original = ingest_email(
        db,
        provider="gmail",
        tenant_id="tenant-a",
        email={
            "message_id": "rotate-1",
            "from_addr": "supplier@example.test",
            "body": "raw quote evidence",
            "attachments": [],
        },
        security_evaluator=lambda *_args, **_kwargs: {"route": "security_review"},
    )
    loaded = load_raw_evidence(
        db,
        tenant_id="tenant-a",
        evidence_ref=original["raw_evidence_ref"],
        actor_id="owner-1",
        purpose="security investigation",
        inbox_id=original["inbox_id"],
    )
    assert loaded["body"] == "raw quote evidence"
    set_legal_hold(
        db,
        tenant_id="tenant-a",
        evidence_ref=original["raw_evidence_ref"],
        enabled=True,
        actor_id="owner-1",
        purpose="active investigation",
    )

    monkeypatch.setenv(
        "EMAIL_EVIDENCE_KEYS",
        f"v1:{'11' * 32},v2:{'22' * 32}",
    )
    monkeypatch.setenv("EMAIL_EVIDENCE_ACTIVE_KEY_ID", "v2")
    assert rotate_evidence_keys(
        db,
        tenant_id="tenant-a",
        actor_id="owner-1",
        purpose="scheduled key rotation",
    ) == 1
    assert load_raw_evidence(
        db,
        tenant_id="tenant-a",
        evidence_ref=original["raw_evidence_ref"],
        actor_id="owner-1",
        purpose="post-rotation verification",
    )["body"] == "raw quote evidence"
    actions = [
        row[0]
        for row in db.execute(
            text("SELECT action FROM email_evidence_operation_audit ORDER BY created_at, id")
        ).fetchall()
    ]
    assert actions.count("read") == 2
    assert "legal_hold_enabled" in actions
    assert "key_rotated" in actions
