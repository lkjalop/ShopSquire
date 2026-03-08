from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_prompt_injection_corpus_endpoint_lists_cases():
    app = create_app()
    client = TestClient(app)

    r = client.get("/api/v1/email_security/prompt-injection/corpus", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert int(body.get("count") or 0) >= 5
    cases = body.get("cases") or []
    assert isinstance(cases, list)
    assert any(str(c.get("id") or "").startswith("pi-") for c in cases)


def test_prompt_injection_run_endpoint_writes_report(tmp_path: Path):
    app = create_app()
    client = TestClient(app)

    report_path = tmp_path / "prompt_injection_eval_report.json"
    r = client.post(
        "/api/v1/email_security/prompt-injection/run",
        json={"tenant_id": "tenant-pi-eval", "persist_report": True, "report_path": str(report_path)},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    summary = body.get("summary") or {}
    assert int(summary.get("total") or 0) >= 5
    assert "precision" in summary
    assert "recall" in summary
    assert str(body.get("report_path") or "").endswith(".json")
    assert "repro_command" in body

    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert "summary" in data
    assert "cases" in data
