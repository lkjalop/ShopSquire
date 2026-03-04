from src.app.services.recommendations import RecommendationService
from src.app.routers import recommend as recommend_router
from src.app.services.memory import Memory
from src.app.deps import get_redis
from tests.test_recommend import client, _write_flags


def test_recommend_includes_fraud_summary_from_tls_geo_context(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    captured = {"session_data": None}
    events = []
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
        monkeypatch.setattr(
            recommend_router,
            "log_trace_event",
            lambda *args, **kwargs: events.append(
                {
                    "event_type": kwargs.get("event_type"),
                    "payload": kwargs.get("payload") or {},
                }
            ),
        )

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
        fraud_events = [e for e in events if str(e.get("event_type") or "") == "fraud_score"]
        assert fraud_events, "Expected fraud_score trace event"
        assert float((fraud_events[-1].get("payload") or {}).get("score") or 0.0) == 0.91
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_persists_last_geoip_country_and_asn(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "FR-2", "name": "Laptop C", "price_cents": 109900, "currency": "USD", "stock": 2, "specs": {"ram_gb": 16}},
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
        uid = "u-fraud-persist-1"
        monkeypatch.setattr(
            recommend_router,
            "extract_tls_fingerprints_from_request",
            lambda req: {"source_ip": "203.0.113.9"},
        )

        import src.app.services.geoip as geoip_mod

        monkeypatch.setattr(
            geoip_mod,
            "enrich_ip",
            lambda ip: {"country": "US", "asn": 64512, "risk": 0.25, "is_hosting": False, "is_vpn": False},
            raising=True,
        )

        class _StubFraudScorer:
            def score_with_enrichment(self, base_signals, expected_serial, observed_serial, image_phash, session_data=None, case_id=None):
                return 0.33, "low", {"geoip_country_mismatch": False}

        monkeypatch.setattr(recommend_router, "FraudScorer", _StubFraudScorer)

        r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "recommend me a laptop"})
        assert r.status_code == 200
        mem = Memory(get_redis())
        kv = mem.get_kv(uid) or {}
        assert str(kv.get("last_ip_country") or "") == "US"
        assert int(kv.get("last_asn") or 0) == 64512
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_fraud_negative_path_handles_missing_geo_tls(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    captured = {"session_data": None}
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "FR-3", "name": "Laptop D", "price_cents": 89900, "currency": "USD", "stock": 5, "specs": {"ram_gb": 8}},
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
        monkeypatch.setattr(recommend_router, "extract_tls_fingerprints_from_request", lambda req: {})
        import src.app.services.geoip as geoip_mod

        monkeypatch.setattr(
            geoip_mod,
            "enrich_ip",
            lambda ip: (_ for _ in ()).throw(RuntimeError("geoip_down")),
            raising=True,
        )
        class _StubFraudScorer:
            def score_with_enrichment(self, base_signals, expected_serial, observed_serial, image_phash, session_data=None, case_id=None):
                captured["session_data"] = dict(session_data or {})
                return 0.05, "minimal", {}

        monkeypatch.setattr(recommend_router, "FraudScorer", _StubFraudScorer)

        r = client.get("/api/v1/recommend/suggest", params={"uid": "u-fraud-negative-1", "query": "budget laptop"})
        assert r.status_code == 200
        body = r.json()
        fraud = body.get("fraud") or {}
        assert isinstance(fraud, dict)
        sd = captured.get("session_data") or {}
        assert sd.get("ja3_hash") in (None, "")
        assert sd.get("ja4_hash") in (None, "")
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_emits_system_error_trace_when_geoip_enrichment_fails(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    events = []
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "FR-4", "name": "Laptop E", "price_cents": 99900, "currency": "USD", "stock": 3, "specs": {"ram_gb": 16}},
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
        monkeypatch.setattr(
            recommend_router,
            "extract_tls_fingerprints_from_request",
            lambda req: {"source_ip": "203.0.113.19"},
        )
        import src.app.services.geoip as geoip_mod

        monkeypatch.setattr(
            geoip_mod,
            "enrich_ip",
            lambda ip: (_ for _ in ()).throw(RuntimeError("geoip_down")),
            raising=True,
        )

        class _StubFraudScorer:
            def score_with_enrichment(self, base_signals, expected_serial, observed_serial, image_phash, session_data=None, case_id=None):
                return 0.2, "low", {}

        monkeypatch.setattr(recommend_router, "FraudScorer", _StubFraudScorer)
        monkeypatch.setattr(
            recommend_router,
            "log_trace_event",
            lambda *args, **kwargs: events.append({"event_type": kwargs.get("event_type"), "payload": kwargs.get("payload") or {}}),
        )

        r = client.get("/api/v1/recommend/suggest", params={"uid": "u-fraud-geoip-err-1", "query": "laptop"})
        assert r.status_code == 200
        errs = [e for e in events if str(e.get("event_type") or "") == "system_error"]
        assert errs
        assert any(str((e.get("payload") or {}).get("stage") or "") == "fraud_session.geoip" for e in errs)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
