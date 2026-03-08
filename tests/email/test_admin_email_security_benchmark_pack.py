from fastapi.testclient import TestClient

from src.app.main import create_app


def test_adversarial_generate_and_external_benchmark_run(tmp_path):
    app = create_app()
    client = TestClient(app)

    gen = client.post(
        "/api/v1/admin/email_security/adversarial/generate",
        json={"n": 8, "seed": 13},
        headers={"x-api-key": "local-owner-key"},
    )
    assert gen.status_code == 200
    g = gen.json()
    assert g.get("status") == "ok"
    assert int(g.get("count") or 0) == 8
    assert isinstance(g.get("rows"), list)

    path = tmp_path / "external_benchmark_pack_v1.json"
    run = client.post(
        "/api/v1/admin/email_security/benchmarks/external/run",
        json={"tenant_id": "bench-tenant", "persist_report": True, "report_path": str(path), "n": 8, "seed": 13},
        headers={"x-api-key": "local-owner-key"},
    )
    assert run.status_code == 200
    r = run.json()
    assert r.get("status") == "ok"
    summary = r.get("summary") or {}
    assert int(summary.get("total") or 0) == 8
    assert "precision" in summary
    assert "recall" in summary
    assert "fpr" in summary
    assert path.exists()
