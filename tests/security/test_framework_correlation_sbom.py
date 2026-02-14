import os
import json

from src.app.security.framework_correlation import correlate_security_analysis


def test_sbom_snapshot_present_when_path_set(tmp_path, monkeypatch):
    # Create a dummy sbom.json and point SBOM_PATH to it
    sbom_file = tmp_path / "sbom.json"
    sbom_file.write_text(json.dumps({"components": [], "vulnerabilities": []}))
    monkeypatch.setenv("SBOM_PATH", str(sbom_file))

    out = correlate_security_analysis(
        channel="email",
        severity="warning",
        tags=["supply_chain"],
        reasons=["dependency update"],
        threat_correlation={},
        signals={"supply_chain": True},
        evidence={}
    )
    sbom = out.get("sbom") or {}
    assert sbom.get("sbom_path")
    py = sbom.get("python_manifest") or {}
    assert "path" in py and "sha256" in py


def test_sbom_snapshot_unknown_when_missing(monkeypatch):
    # Ensure SBOM_PATH unset and file absent
    monkeypatch.delenv("SBOM_PATH", raising=False)
    out = correlate_security_analysis(
        channel="email",
        severity="info",
        tags=[],
        reasons=[],
        threat_correlation={},
        signals={},
        evidence={}
    )
    sbom = out.get("sbom") or {}
    assert sbom.get("sbom_path") in (None, "sbom.json")
