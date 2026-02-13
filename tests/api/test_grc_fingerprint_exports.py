from fastapi.testclient import TestClient

from src.app.main import create_app


def test_grc_fingerprint_ingest_alerts_and_status(monkeypatch):
    monkeypatch.setenv("FINGERPRINT_SCAN_TARGETS_HEADERS", "not-a-url")
    monkeypatch.delenv("FINGERPRINT_SCAN_TARGETS_TLS", raising=False)
    monkeypatch.delenv("FINGERPRINT_SCAN_TARGETS_SSH", raising=False)

    client = TestClient(create_app(), headers={"x-api-key": "local-owner-key"})
    run = client.post("/api/v1/admin/grc/fingerprint-ingest/run")
    assert run.status_code == 200
    body = run.json()
    assert body.get("scans", 0) >= 1

    alerts = client.get("/api/v1/admin/grc/fingerprint-alerts?limit=20")
    assert alerts.status_code == 200
    items = alerts.json().get("items", [])
    assert isinstance(items, list)
    assert len(items) >= 1
    alert_id = items[0]["id"]

    upd = client.post(f"/api/v1/admin/grc/fingerprint-alerts/{alert_id}/status?status=resolved&note=test-fix")
    assert upd.status_code == 200
    assert upd.json().get("status") == "resolved"


def test_grc_report_exports_and_trends():
    client = TestClient(create_app(), headers={"x-api-key": "local-owner-key"})

    trend = client.get("/api/v1/admin/grc/trends?days=7")
    assert trend.status_code == 200
    tb = trend.json()
    assert tb.get("days") == 7
    assert "series" in tb

    csv_r = client.get("/api/v1/admin/grc/report/export.csv?days=7")
    assert csv_r.status_code == 200
    assert "text/csv" in (csv_r.headers.get("content-type") or "")
    assert "section,key,value" in csv_r.text

    md_r = client.get("/api/v1/admin/grc/report/export.md?days=7")
    assert md_r.status_code == 200
    assert "text/markdown" in (md_r.headers.get("content-type") or "")
    assert "# ShopSquire GRC Report" in md_r.text

    pdf_r = client.get("/api/v1/admin/grc/report/export.pdf?days=7")
    assert pdf_r.status_code == 200
    assert "application/pdf" in (pdf_r.headers.get("content-type") or "")
    assert pdf_r.content.startswith(b"%PDF-1.4")

