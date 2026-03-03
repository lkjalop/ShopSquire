from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.main import create_app


_ARTIFACTS = [
    "BEC-02_compromised_supplier_email.eml",
    "BEC-04_macro_invoice_specification.md",
    "EXECUTIVE_SUMMARY.md",
    "generate_adversarial_invoices.py",
    "invoice_adv_dct.png",
    "invoice_adv_fgsm.png",
    "invoice_adv_FULL_COMBO.png",
    "invoice_adv_logo.png",
    "invoice_adv_subtle.png",
    "invoice_baseline.png",
    "shopsquire_invoice_test_scenarios.md",
    "shopsquire_testing_guide_comprehensive.md",
]


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "dump" / "email-2" / "files"


def test_email2_fixture_replay_is_deterministic():
    base = _fixture_dir()
    if not base.exists():
        # CI/local variants may omit large fixture bundle.
        return
    files = []
    for name in _ARTIFACTS:
        p = base / name
        assert p.exists(), f"missing fixture artifact: {p}"
        b = p.read_bytes()
        files.append(
            {
                "name": name,
                "size_bytes": len(b),
                "sha256": hashlib.sha256(b).hexdigest(),
            }
        )
    files = sorted(files, key=lambda x: x["name"])
    fixture_hash = hashlib.sha256(
        "|".join([f"{f['name']}:{f['sha256']}" for f in files]).encode("utf-8")
    ).hexdigest()

    payload = {
        "vendor": "siem",
        "storage_targets": ["database"],
        "event": {
            "event_id": f"email2-fixture-{fixture_hash[:16]}",
            "trace_id": f"trace-email2-{fixture_hash[:12]}",
            "tenant_id": "tenant-email2-fixture",
            "event_type": "phish",
            "severity": "critical",
            "confidence": 0.96,
            "artifacts": files,
            "fixture_hash": fixture_hash,
        },
    }

    client = TestClient(create_app())
    first = client.post("/api/v1/security/events/ingest", headers={"x-api-key": "local-owner-key"}, json=payload)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body.get("ok") is True
    assert ((first_body.get("policy") or {}).get("action")) == "block"

    second = client.post("/api/v1/security/events/ingest", headers={"x-api-key": "local-owner-key"}, json=payload)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body.get("deduped") is True
    assert second_body.get("id") == first_body.get("id")

    replay = client.get(
        f"/api/v1/security/events/replay/{first_body.get('id')}",
        headers={"x-api-key": "local-owner-key"},
    )
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()
    assert replay_body.get("deterministic_match") is True
