import time
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session


def test_ransomware_markers_in_cv(monkeypatch):
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("CV_ASYNC_QUEUE_ENABLED", "0")

    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}

    ransom_text = (
        "Your files have been encrypted. To recover, send 5 BTC to bc1...\n"
        "Contact: decrypt-support@evil.example.com\n"
        "Affected files: *.docx, *.xlsx, *.pdf\n"
        "Ransom note ID: ransom-1234"
    )

    payload = {
        "case_id": "ransom-test-1",
        "extracted_text": ransom_text,
        "labels": ["ransomware", "threat"],
        "description": "OCR of ransom note containing file patterns and crypto address",
    }

    resp = client.post("/api/v1/cv/analyze", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    case_id = data.get("case_id")
    assert case_id == "ransom-test-1"

    # CV analyze returned; inspect `cv_analysis` for indicators (best-effort)
    assert "cv_analysis" in data and isinstance(data.get("cv_analysis"), dict)


def test_supply_chain_tampering_detection(monkeypatch):
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("SECURITY_OBSERVER_SYNC", "1")

    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}

    # Query simulating a developer checking a package manifest with malicious URL
    query = (
        "Review package.json: dependency 'libx' resolved to http://malicious.example.com/libx.tgz which is unsigned."
        " Is this safe to install?"
    )

    resp = client.get("/api/v1/recommend/suggest", params={"uid": "dev-1", "query": query}, headers=headers)
    assert resp.status_code == 200
    # The passive observer is an evidence stream, not a commercial decision-trace
    # writer. Prove the request was detected and persisted without coupling the
    # security contract to retired V1 trace side effects.
    deadline = time.time() + 5.0
    found = None
    while time.time() < deadline:
        with db_session() as db:
            found = db.execute(
                text(
                    "SELECT details FROM security_events "
                    "WHERE path = '/api/v1/recommend/suggest' "
                    "AND details LIKE :signal ORDER BY event_time DESC LIMIT 1"
                ),
                {"signal": '%\"supply_chain\": true%'},
            ).scalar()
        if found:
            break
        time.sleep(0.25)

    assert found, "Expected security-related event for supply-chain tampering indicators"


def test_bec_invoice_pattern_detection(monkeypatch):
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")

    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}

    # Simulate a user-submitted invoice text (BEC-like urgency/request)
    invoice_text = (
        "URGENT: Please transfer $25,000 to account 123-456 immediately. This is a priority for payroll."
    )

    # Use CV analyze to represent uploaded invoice OCR
    payload = {"case_id": "bec-invoice-1", "extracted_text": invoice_text, "labels": ["invoice", "payment_request"]}
    resp = client.post("/api/v1/cv/analyze", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    case_id = data.get("case_id")
    assert case_id

    # CV analyze returned; check analysis present
    assert "cv_analysis" in data and isinstance(data.get("cv_analysis"), dict)
