import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.email_connector_identity import ConnectorIdentity
from src.app.services.supplier_observation_projection import (
    project_governed_supplier_inbox,
)


def _db() -> Session:
    db = Session(create_engine("sqlite:///:memory:"))
    db.execute(text("""
        CREATE TABLE inbound_email_inbox (
          id TEXT PRIMARY KEY, tenant_id TEXT, provider TEXT,
          subscription_id TEXT, provider_message_id TEXT,
          fulfillment_case_id TEXT, status TEXT, security_route TEXT,
          sanitized_payload_json TEXT, security_verdict_json TEXT,
          raw_evidence_ref TEXT, received_at TIMESTAMP
        )
    """))
    db.execute(text("""
        CREATE TABLE causal_impact_hypothesis (
          id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, created_at TIMESTAMP
        )
    """))
    db.execute(text("""
        CREATE TABLE supplier_hypothesis_observation (
          id TEXT PRIMARY KEY, tenant_id TEXT, hypothesis_id TEXT,
          observation_type TEXT, supplier_ref TEXT, source_message_id TEXT,
          observation_json TEXT, provenance_json TEXT, observed_at TIMESTAMP,
          recorded_by TEXT, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(tenant_id,source_message_id,hypothesis_id)
        )
    """))
    return db


def _seed(db: Session, *, status: str = "case_correlated", route: str = "allow") -> None:
    now = datetime.now(timezone.utc)
    db.execute(text("""
        INSERT INTO causal_impact_hypothesis
        (id,tenant_id,case_id,created_at)
        VALUES ('hyp-1','tenant-a','case-1',:now)
    """), {"now": now})
    db.execute(text("""
        INSERT INTO inbound_email_inbox
        (id,tenant_id,provider,subscription_id,provider_message_id,
         fulfillment_case_id,status,security_route,sanitized_payload_json,
         security_verdict_json,raw_evidence_ref,received_at)
        VALUES
        ('inbox-1','tenant-a','gmail','sub-1','message-1','case-1',
         :status,:route,:payload,:verdict,'evidence-1',:now)
    """), {
        "status": status,
        "route": route,
        "payload": json.dumps({
            "from_addr": "sales@supplier.example",
            "subject": "Allocation update",
            "body": "We cannot confirm full capacity; only 60 units are available.",
        }),
        "verdict": json.dumps({"route": route, "reasons": []}),
        "now": now,
    })
    db.commit()


def _identity() -> ConnectorIdentity:
    return ConnectorIdentity("gmail", "sub-1", "tenant-a", {})


def test_verified_accepted_reply_projects_idempotent_observation_only() -> None:
    db = _db()
    _seed(db)
    first = project_governed_supplier_inbox(
        db, inbox_id="inbox-1", connector_identity=_identity(),
        transport_identity_verified=True,
    )
    second = project_governed_supplier_inbox(
        db, inbox_id="inbox-1", connector_identity=_identity(),
        transport_identity_verified=True,
    )
    assert first["status"] == "projected_observation_only"
    assert first["supplier_observation"]["observation_type"] == "contradiction"
    assert first["execution_allowed"] is False
    assert second["supplier_observation"]["idempotent_replay"] is True
    assert db.execute(text(
        "SELECT COUNT(*) FROM supplier_hypothesis_observation"
    )).scalar_one() == 1


def test_quarantined_or_unverified_reply_cannot_project() -> None:
    db = _db()
    _seed(db, status="case_quarantined", route="security_review")
    quarantined = project_governed_supplier_inbox(
        db, inbox_id="inbox-1", connector_identity=_identity(),
        transport_identity_verified=True,
    )
    unverified = project_governed_supplier_inbox(
        db, inbox_id="inbox-1", connector_identity=_identity(),
        transport_identity_verified=False,
    )
    assert quarantined["projected"] is False
    assert unverified["status"] == "blocked_unverified_transport_identity"
    assert db.execute(text(
        "SELECT COUNT(*) FROM supplier_hypothesis_observation"
    )).scalar_one() == 0


def test_cross_tenant_or_subscription_identity_is_rejected() -> None:
    db = _db()
    _seed(db)
    wrong = ConnectorIdentity("gmail", "other-sub", "tenant-a", {})
    try:
        project_governed_supplier_inbox(
            db, inbox_id="inbox-1", connector_identity=wrong,
            transport_identity_verified=True,
        )
    except ValueError as exc:
        assert str(exc) == "supplier_inbox_connector_identity_mismatch"
    else:
        raise AssertionError("identity mismatch should fail closed")
