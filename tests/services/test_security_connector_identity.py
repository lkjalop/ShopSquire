from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import security_connector_identity as identity
from src.app.security.security_event_ingest import normalize_vendor_payload


@pytest.fixture()
def connector_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE security_connector_subscription (
                connector_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                credential_hash TEXT NOT NULL,
                allowed_event_families_json TEXT NOT NULL,
                allowed_source_ids_json TEXT NOT NULL,
                permitted_storage_targets_json TEXT NOT NULL,
                permitted_response_actions_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                credential_expires_at TEXT,
                last_seen_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """))
    factory = sessionmaker(bind=engine, class_=Session, future=True)

    @contextmanager
    def scoped_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(identity, "db_session", scoped_session)
    monkeypatch.setenv("SECURITY_CONNECTOR_CREDENTIAL_PEPPER", "test-pepper")
    return engine


def _register(**overrides):
    values = {
        "connector_id": "connector-a",
        "tenant_id": "tenant-a",
        "provider": "crowdstrike",
        "bearer_secret": "correct-secret",
        "allowed_event_families": ["network"],
        "allowed_source_ids": ["sensor-1"],
        "storage_targets": ["database"],
        "response_actions": ["alert"],
    }
    values.update(overrides)
    return identity.register_security_connector(**values)


def test_registered_connector_authenticates_exact_tenant_family_and_source(connector_db):
    _register()

    authenticated = identity.authenticate_security_connector(
        connector_id="connector-a",
        bearer_secret="correct-secret",
        event_family="network",
        source_id="sensor-1",
    )

    assert authenticated.tenant_id == "tenant-a"
    assert authenticated.provider == "crowdstrike"
    assert authenticated.storage_targets == ("database",)


@pytest.mark.parametrize(
    ("secret", "family", "source", "error"),
    [
        ("wrong", "network", "sensor-1", "invalid_security_connector_credential"),
        ("correct-secret", "process", "sensor-1", "security_connector_event_family_denied"),
        ("correct-secret", "network", "sensor-2", "security_connector_source_denied"),
    ],
)
def test_connector_authentication_fails_closed(connector_db, secret, family, source, error):
    _register()

    with pytest.raises(ValueError, match=error):
        identity.authenticate_security_connector(
            connector_id="connector-a",
            bearer_secret=secret,
            event_family=family,
            source_id=source,
        )


def test_expired_connector_credential_is_rejected(connector_db):
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _register(credential_expires_at=expired)

    with pytest.raises(ValueError, match="expired_security_connector_credential"):
        identity.authenticate_security_connector(
            connector_id="connector-a",
            bearer_secret="correct-secret",
            event_family="network",
            source_id="sensor-1",
        )


def test_authenticated_tenant_overrides_untrusted_payload_claim() -> None:
    canonical = normalize_vendor_payload(
        "siem",
        {"tenant_id": "payload-tenant", "event_id": "evt-1", "type": "network"},
        authoritative_tenant_id="connector-tenant",
    )

    assert canonical["tenant_id"] == "connector-tenant"
    assert canonical["untrusted_claimed_tenant_id"] == "payload-tenant"
    assert canonical["tenant_authority"] == "authenticated_connector_or_request_context"
