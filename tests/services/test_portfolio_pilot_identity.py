from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.portfolio_pilot_identity import (
    enrol_pilot_identities,
    load_pilot_identity_profile,
    pilot_identity_readiness,
)


def _membership_schema(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE operator_tenant_membership (
          principal_hash TEXT NOT NULL,
          tenant_id TEXT NOT NULL,
          role TEXT NOT NULL,
          subject_id TEXT,
          auth_method TEXT NOT NULL,
          status TEXT NOT NULL,
          created_by TEXT NOT NULL,
          created_at TIMESTAMP NOT NULL,
          updated_at TIMESTAMP NOT NULL,
          revoked_at TIMESTAMP,
          PRIMARY KEY (principal_hash, tenant_id)
        )
    """))
    db.commit()


def test_profile_is_non_production_and_synthetic_only() -> None:
    profile = load_pilot_identity_profile()
    assert profile.tenant_id == "portfolio-demo"
    assert profile.production_authority is False
    assert profile.supplier_mode == "synthetic_only"
    assert profile.real_supplier_send_authorized is False
    assert {item.role for item in profile.principals} == {"merchant", "owner", "developer"}


def test_enrolment_requires_every_external_credential(monkeypatch, tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    payload = json.loads(Path("config/portfolio_pilot_identities.json").read_text(encoding="utf-8"))
    profile_path.write_text(json.dumps(payload), encoding="utf-8")
    profile = load_pilot_identity_profile(profile_path)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as db:
        _membership_schema(db)
        monkeypatch.delenv("OWNER_API_KEY", raising=False)
        monkeypatch.setenv("MERCHANT_API_KEY", "buyer-secret")
        monkeypatch.setenv("DEVELOPER_API_KEY", "engineer-secret")
        with pytest.raises(ValueError, match="missing_pilot_credentials:OWNER_API_KEY"):
            enrol_pilot_identities(db, profile)


def test_enrolment_persists_server_derived_subjects_without_returning_secrets(monkeypatch) -> None:
    profile = load_pilot_identity_profile()
    for env_name, secret in {
        "MERCHANT_API_KEY": "buyer-secret",
        "OWNER_API_KEY": "owner-secret",
        "DEVELOPER_API_KEY": "engineer-secret",
    }.items():
        monkeypatch.setenv(env_name, secret)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as db:
        _membership_schema(db)
        result = enrol_pilot_identities(db, profile)
        readiness = pilot_identity_readiness(db, profile)
    assert readiness["ready"] is True
    assert readiness["identity_source"] == "server_persisted_membership"
    assert all(item["status"] == "active" for item in readiness["principals"])
    rendered = json.dumps(result)
    assert "buyer-secret" not in rendered
    assert "owner-secret" not in rendered
    assert result["real_supplier_send_authorized"] is False
