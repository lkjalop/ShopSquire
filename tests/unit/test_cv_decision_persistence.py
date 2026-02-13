import pytest
from fastapi.testclient import TestClient
from src.app.main import create_app


class FakeTiered:
    def __init__(self, flags=None):
        pass

    async def analyze(self, labels, extracted_text, context=None):
        # Return a high-severity verdict to trigger decision persistence
        return {"verdict": {"severity": "high", "required_actions": ["human_review"]}, "forensics": {}}


def test_cv_high_severity_triggers_decision_persistence(monkeypatch):
    # Ensure any real DB writes are not attempted; capture log_decision calls
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")

    # Replace provider and persistence helpers
    monkeypatch.setattr("src.app.routers.cv.TieredCVProvider", FakeTiered)
    monkeypatch.setattr("src.app.routers.cv.persist_cv_analysis", lambda *args, **kwargs: None)
    monkeypatch.setattr("src.app.routers.cv.build_evidence_bundle", lambda *args, **kwargs: {"dummy": True})
    monkeypatch.setattr("src.app.routers.cv.persist_evidence_bundle", lambda case_id, bundle: "evidence-123")

    calls = []

    def fake_log_decision(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return kwargs.get("decision_id") or "fake-id"

    monkeypatch.setattr("src.app.routers.cv.log_decision", fake_log_decision)

    app = create_app()
    client = TestClient(app)

    payload = {"case_id": "unit-cv-1", "extracted_text": "ransom note sample", "labels": ["ransomware"]}
    resp = client.post("/api/v1/cv/analyze", json=payload, headers={"x-api-key": "local-merchant-key"})
    assert resp.status_code == 200, resp.text
    assert calls, "expected log_decision to be called"
    # Verify decision_id matches case_id
    called_kwargs = calls[0]["kwargs"]
    assert called_kwargs.get("decision_id") == "unit-cv-1"
