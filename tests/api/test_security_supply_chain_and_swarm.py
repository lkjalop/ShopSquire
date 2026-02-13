from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import base64
import hashlib
import hmac

from src.app.main import create_app
from src.app.models.db import set_engine


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "security_supply_chain.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    return TestClient(create_app())


def test_supply_chain_sbom_oauth_and_artifact_endpoints(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    sbom = {
        "components": [{"name": "liblzma", "version": "5.6.1"}],
        "vulnerabilities": [{"id": "CVE-2024-3094"}],
    }
    r1 = client.post("/api/v1/security/supply_chain/sbom/ingest", json={"tenant_id": "t1", "sbom": sbom}, headers={"x-api-key": "local-owner-key"})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1.get("risk_band") == "high"
    assert "CVE-2024-3094" in (b1.get("kev_hits") or [])

    r2 = client.post(
        "/api/v1/security/supply_chain/oauth/scope/check",
        json={"tenant_id": "t1", "partner": "erp-sync", "baseline_scopes": ["read:orders"], "granted_scopes": ["read:orders", "admin:billing"]},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert "admin:billing" in (b2.get("high_risk_scopes") or [])
    assert b2.get("requires_security_review") is True

    monkeypatch.setenv("ARTIFACT_SIGNATURE_MODE", "hmac")
    monkeypatch.setenv("PARTNER_ARTIFACT_HMAC_SECRET", "test-secret")
    monkeypatch.setenv("TRUSTED_PARTNER_SIGNERS", "trusted-partner")
    blob = b"release-artifact-v1"
    sig = hmac.new(b"test-secret", blob, hashlib.sha256).hexdigest()
    r3 = client.post(
        "/api/v1/security/supply_chain/artifact/verify",
        json={"artifact_b64": base64.b64encode(blob).decode("utf-8"), "signature": sig, "signer": "trusted-partner", "algorithm": "sha256"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r3.status_code == 200
    b3 = r3.json()
    assert b3.get("signature_verified") is True
    assert b3.get("signer_trusted") is True
    assert b3.get("requires_security_review") is False

    slsa_att = {
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "builder": {"id": "https://github.com/actions/runner"},
            "buildType": "https://github.com/Workflow",
            "materials": [{"uri": "git+https://github.com/org/repo", "digest": {"sha1": "abc"}}],
        },
    }
    r4 = client.post(
        "/api/v1/security/supply_chain/slsa/verify",
        json={"attestation": slsa_att, "sbom": sbom},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r4.status_code == 200
    b4 = r4.json()
    assert b4.get("slsa_level_estimate") >= 2
    assert b4.get("risk_band") in ("low", "medium", "high")
    assert isinstance(b4.get("checks"), list)


def test_redteam_swarm_start_and_status(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r1 = client.post("/api/v1/security/redteam/swarm/start?rounds=1&max_mutations_per_case=2", headers={"x-api-key": "local-owner-key"})
    assert r1.status_code == 200
    job = r1.json()
    assert job.get("job_id")
    r2 = client.get(f"/api/v1/security/redteam/swarm/{job['job_id']}", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2.get("status") in ("queued", "running", "completed")
