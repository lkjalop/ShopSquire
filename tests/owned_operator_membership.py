"""Opt-in persisted operator grants for disposable test runtimes."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.services.operator_tenant_membership import grant_membership, principal_hash_for_api_key


@pytest.fixture
def owned_operator_client(monkeypatch):
    """Return clients authorized only for each explicitly requested tenant."""
    from src.app.main import create_app

    monkeypatch.setenv("OPERATOR_TENANT_MEMBERSHIP_MODE", "strict")
    clients = []
    grants = []

    def create(tenant_id, *, role="owner"):
        environment = {"owner": "OWNER_API_KEY", "developer": "DEVELOPER_API_KEY", "merchant": "MERCHANT_API_KEY"}
        key = f"owned-operator-test-{uuid.uuid4().hex}"
        monkeypatch.setenv(environment[role], key)
        app = create_app()
        principal = principal_hash_for_api_key(key)
        with Session(app.state.engine) as db:
            grant_membership(db, principal_hash=principal, tenant_id=tenant_id, role=role,
                             auth_method="api_key", created_by="owned-test-fixture")
            db.commit()
        grants.append((app.state.engine, principal))
        client = TestClient(app)
        clients.append(client)
        return client, {"x-api-key": key, "x-tenant-id": tenant_id}

    try:
        yield create
    finally:
        for client in clients:
            client.close()
        for engine, principal in grants:
            with Session(engine) as db:
                db.execute(text("DELETE FROM operator_tenant_membership WHERE principal_hash=:principal"),
                           {"principal": principal})
                db.commit()
