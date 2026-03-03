from src.app.services.recommendations import RecommendationService
from src.app.routers import recommend as recommend_router
from tests.test_recommend import client, _write_flags


def test_recommend_includes_fraud_summary_from_tls_geo_context(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    captured = {"session_data": None}
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "FR-1", "name": "Laptop A", "price_cents": 99900, "currency": "USD", "stock": 2, "specs": {"ram_gb": 16}},
        ]
        _write_flags(
            {
                "USE_AGENT_CAPABILITIES": True,
                "AGENT_ROLLOUT_PERCENT": 100,
                "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
                "KILL_SWITCH": False,
                "DECISION_LOG_WRITES_ENABLED": False,
                "DEGRADATION": {"enabled": True},
                "TEST_FORCE_BAD_SKU": False,
            }
        )
        monkeypatch.setenv("FRAUD_KNOWN_JA3_HASHES", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        monkeypatch.setenv("FRAUD_KNOWN_JA4_HASHES", "bbbbbbbbbbbbbbbb")
        monkeypatch.setattr(
            recommend_router,
            "extract_tls_fingerprints_from_request",
            lambda req: {
                "source_ip": "203.0.113.5",
                "trusted_proxy_source": True,
                "ja3_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "ja4_hash": "bbbbbbbbbbbbbbbb",
            },
        )

        class _StubFraudScorer:
            def score_with_enrichment(self, base_signals, expected_serial, observed_serial, image_phash, session_data=None, case_id=None):
                captured["session_data"] = dict(session_data or {})
                return 0.91, "high", {"ja3_known_fraud_tool": True, "geoip_high_risk_country": True}

        monkeypatch.setattr(recommend_router, "FraudScorer", _StubFraudScorer)

        r = client.get("/api/v1/recommend/suggest", params={"uid": "u-fraud-summary-1", "query": "show me laptops under $1200"})
        assert r.status_code == 200
        body = r.json()
        fraud = body.get("fraud") or {}
        assert float(fraud.get("score") or 0.0) == 0.91
        assert str(fraud.get("level") or "") == "high"
        assert bool((fraud.get("signals") or {}).get("ja3_known_fraud_tool")) is True
        sd = captured.get("session_data") or {}
        assert sd.get("ja3_hash") == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert sd.get("ja4_hash") == "bbbbbbbbbbbbbbbb"
        assert sd.get("source_ip") == "203.0.113.5"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
