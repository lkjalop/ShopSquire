import json

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


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text(_DDL))
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
    assert row[1].startswith("sha256:")


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
