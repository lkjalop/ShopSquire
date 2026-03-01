import base64
import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app


def _headers() -> dict:
    return {"x-api-key": "local-merchant-key"}


def _tiny_png_b64() -> str:
    # 1x1 PNG
    blob = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO0i4t8AAAAASUVORK5CYII="
    )
    return base64.b64encode(blob).decode("ascii")


def test_cv_analyze_propagates_tier2_security_tags(monkeypatch, tmp_path):
    db_file = tmp_path / "cv_analyze_tags.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")
    monkeypatch.setenv("CV_ASYNC_QUEUE_ENABLED", "0")

    monkeypatch.setattr(
        "src.app.routers.cv.strict_image_ingest_gate",
        lambda **kwargs: {"blocked": False},
    )

    def _fake_sanitize(blob: bytes):
        return {
            "status": "sanitized",
            "bytes": blob,
            "filename": "analyze_1.jpg",
        }

    monkeypatch.setattr("src.app.services.image_intake.sanitize_image", _fake_sanitize)

    async def _fake_labels_text(self, image_bytes: bytes):
        return ["laptop"], "demo text"

    monkeypatch.setattr(
        "src.app.services.cv_provider.ManagedCVProvider.get_labels_and_text",
        _fake_labels_text,
    )

    monkeypatch.setattr(
        "src.app.routers.cv.run_tier2",
        lambda image_bytes, meta=None, pack_id=None: {
            "evidence_tags": ["qr_url_present", "prompt_injection_text_suspected"],
            "security_analysis": {"severity": "high", "signals": {"qr_url_present": True}},
            "verdict": {"verdict": "request_more_data"},
        },
    )

    app = create_app()
    client = TestClient(app)

    case_id = f"cv-analyze-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/cv/analyze",
        headers=_headers(),
        json={
            "case_id": case_id,
            "images_b64": [_tiny_png_b64()],
            "description": "test",
            "issue_type": "refund",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "qr_url_present" in (body.get("evidence_tags") or [])
    assert bool((body.get("ui_actions") or {}).get("chat_with_admin")) is True


def test_recommend_feedback_endpoint_accepts_correction(monkeypatch, tmp_path):
    db_file = tmp_path / "recommend_feedback.sqlite"
    db_url = f"sqlite+pysqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DATABASE_URL_RO", db_url)
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")

    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/recommend/feedback",
        headers=_headers(),
        json={
            "uid": "demo-user",
            "trace_id": f"trace-{uuid.uuid4().hex[:6]}",
            "sku": "SKU-123",
            "outcome": "corrected",
            "correction_text": "I wanted a MacBook alternative, not gaming laptops.",
            "context": {"surface": "chat"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "ok"
    assert body.get("outcome") == "corrected"


def test_sentiment_nqe_adapter_reduces_questions():
    from src.app.routers.recommend import _adapt_nqe_questions_for_sentiment

    qs = [
        {"id": "ask_budget", "text": "What's your budget?", "goal": "narrow_results"},
        {"id": "ask_use_case", "text": "What do you use it for?", "goal": "narrow_results"},
    ]
    out = _adapt_nqe_questions_for_sentiment(qs, sentiment="frustrated")
    assert len(out) == 1
    assert "frustrating" in str(out[0].get("text") or "").lower()
