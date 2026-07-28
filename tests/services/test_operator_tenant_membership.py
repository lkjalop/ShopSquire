from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.operator_tenant_membership import (
    authorize_membership,
    grant_membership,
    principal_hash_for_api_key,
    principal_hash_for_subject,
    revoke_membership,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE operator_tenant_membership ("
                "principal_hash VARCHAR(64) NOT NULL, tenant_id VARCHAR(128) NOT NULL, "
                "role VARCHAR(64) NOT NULL, subject_id VARCHAR(255), "
                "auth_method VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL, "
                "created_by VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, revoked_at DATETIME, "
                "PRIMARY KEY (principal_hash, tenant_id))"
            )
        )
    with Session(engine) as session:
        yield session


def test_persisted_api_key_membership_is_tenant_and_role_bound(db):
    principal = principal_hash_for_api_key("not-stored-in-database")
    grant_membership(
        db,
        principal_hash=principal,
        tenant_id="tenant-a",
        role="merchant",
        auth_method="api_key",
        created_by="bootstrap",
    )
    db.commit()

    identity = authorize_membership(
        db,
        principal_hash=principal,
        tenant_id="tenant-a",
        authenticated_role="merchant",
        auth_method="api_key",
        strict=True,
    )

    assert identity.persisted is True
    assert identity.tenant_id == "tenant-a"
    stored = db.execute(
        text("SELECT principal_hash FROM operator_tenant_membership")
    ).scalar_one()
    assert stored == principal
    assert "not-stored-in-database" not in stored

    with pytest.raises(HTTPException) as denied:
        authorize_membership(
            db,
            principal_hash=principal,
            tenant_id="tenant-b",
            authenticated_role="merchant",
            auth_method="api_key",
            strict=True,
        )
    assert denied.value.detail == "operator_tenant_membership_required"


def test_role_mismatch_and_revocation_fail_closed(db):
    principal = principal_hash_for_subject("operator-42", issuer="issuer-a")
    grant_membership(
        db,
        principal_hash=principal,
        tenant_id="tenant-a",
        role="owner",
        subject_id="operator-42",
        auth_method="bearer",
        created_by="identity-sync",
    )
    db.commit()

    with pytest.raises(HTTPException) as mismatch:
        authorize_membership(
            db,
            principal_hash=principal,
            tenant_id="tenant-a",
            authenticated_role="merchant",
            subject_id="operator-42",
            auth_method="bearer",
            strict=True,
        )
    assert mismatch.value.detail == "operator_tenant_role_mismatch"

    assert revoke_membership(
        db,
        principal_hash=principal,
        tenant_id="tenant-a",
    )
    db.commit()
    with pytest.raises(HTTPException) as revoked:
        authorize_membership(
            db,
            principal_hash=principal,
            tenant_id="tenant-a",
            authenticated_role="owner",
            subject_id="operator-42",
            auth_method="bearer",
            strict=True,
        )
    assert revoked.value.detail == "operator_tenant_membership_required"
