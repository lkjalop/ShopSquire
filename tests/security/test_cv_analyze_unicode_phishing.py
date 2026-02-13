import time
from fastapi.testclient import TestClient
from src.app.main import create_app


def test_cv_analyze_handles_unicode_and_phishing_text(monkeypatch):
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("CV_ASYNC_QUEUE_ENABLED", "0")

    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}

    extracted = (
        "Dear user, please wire $1000 to account X.\n"
        "This message includes unicode emoji to test parsing: 🚨⚠️✨.\n"
        "Also includes suspicious links: http://malicious.example.com/login"
    )

    payload = {
        "case_id": "cv-test-unicode-1",
        "extracted_text": extracted,
        "labels": ["phishing", "suspicious"],
        "description": "Uploaded screenshot extracted text containing unicode and phishing indicators",
    }

    resp = client.post("/api/v1/cv/analyze", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("status") == "ok"
    assert "cv_analysis" in data

    # Expect a case_id and evidence id
    case_id = data.get("case_id")
    evidence_id = data.get("evidence_id")
    assert case_id
    assert evidence_id
