import json
import os
from fastapi.testclient import TestClient
from src.app.main import app


client = TestClient(app)


def test_scoring_versioning_and_diff_and_rollback():
    # Create a new version
    payload = {"bands": {"warn": 10, "high": 40, "critical": 70}}
    r = client.post("/api/v1/admin/scoring/update", json=payload)
    assert r.status_code == 200
    version = r.json().get("version")
    assert version is not None

    # List versions
    rv = client.get("/api/v1/admin/scoring/versions")
    assert rv.status_code == 200
    versions = rv.json().get("versions")
    assert any(str(version) in v for v in versions)

    # Diff the last two versions if available
    if len(versions) >= 2:
        a, b = versions[-2], versions[-1]
        rd = client.get("/api/v1/admin/scoring/diff", params={"a": a, "b": b})
        assert rd.status_code == 200
        assert "diff" in rd.json()

    # Rollback to the created version
    rr = client.post("/api/v1/admin/scoring/rollback", json={"version_file": versions[-1]})
    assert rr.status_code == 200
    assert rr.json().get("rolled_back") is True
