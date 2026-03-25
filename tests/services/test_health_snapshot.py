"""Tests for extended dependency_health_snapshot()."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def test_health_snapshot_structure():
    """Snapshot must include all 5 dependency keys and overall field."""
    with patch("src.app.observability.health._check_db", return_value={"status": "healthy", "latency_ms": 1}), \
         patch("src.app.observability.health._check_redis", return_value={"status": "healthy", "latency_ms": 1}), \
         patch("src.app.observability.health._check_ollama", return_value={"status": "healthy", "latency_ms": 5}), \
         patch("src.app.observability.health._check_pgvector", return_value={"status": "healthy", "latency_ms": 2}), \
         patch("src.app.observability.health._check_cv_provider", return_value={"status": "healthy", "provider": "openai"}):
        from src.app.observability.health import dependency_health_snapshot
        snap = dependency_health_snapshot(force=True)

    assert "overall" in snap
    assert snap["overall"] == "healthy"
    deps = snap["dependencies"]
    for key in ("db", "redis", "ollama", "pgvector", "cv_provider"):
        assert key in deps, f"Missing dependency key: {key}"


def test_health_snapshot_degraded_when_redis_down():
    with patch("src.app.observability.health._check_db", return_value={"status": "healthy"}), \
         patch("src.app.observability.health._check_redis", return_value={"status": "unhealthy", "error": "conn refused"}), \
         patch("src.app.observability.health._check_ollama", return_value={"status": "healthy"}), \
         patch("src.app.observability.health._check_pgvector", return_value={"status": "healthy"}), \
         patch("src.app.observability.health._check_cv_provider", return_value={"status": "not_configured"}):
        from src.app.observability.health import dependency_health_snapshot
        snap = dependency_health_snapshot(force=True)

    assert snap["overall"] == "degraded"


def test_check_cv_provider_not_configured(monkeypatch):
    import os
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_VISION_MODEL", raising=False)
    from src.app.observability.health import _check_cv_provider
    result = _check_cv_provider()
    assert result["status"] == "not_configured"
    assert result["provider"] is None


def test_check_cv_provider_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    from src.app.observability.health import _check_cv_provider
    result = _check_cv_provider()
    assert result["status"] == "healthy"
    assert result["provider"] == "openai"


def test_check_pgvector_not_migrated():
    from unittest.mock import patch as _patch
    with _patch("src.app.observability.health.db_session") as mock_sess:
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("relation product_embeddings does not exist")
        mock_sess.return_value.__enter__ = lambda s: mock_db
        mock_sess.return_value.__exit__ = MagicMock(return_value=False)
        from src.app.observability.health import _check_pgvector
        result = _check_pgvector()
    assert result["status"] == "not_migrated"
