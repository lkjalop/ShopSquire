from __future__ import annotations

from src.app.services.recommend_fraud_context import (
    evaluate_recommendation_fraud,
)


class _StubFraudScorer:
    def __init__(self, score=0.91, level="high", signals=None):
        self.score = score
        self.level = level
        self.signals = signals or {"ja3_known_fraud_tool": True}
        self.session_data = None

    def score_with_enrichment(self, *_args, session_data=None, **_kwargs):
        self.session_data = dict(session_data or {})
        return self.score, self.level, self.signals


def test_recommend_includes_fraud_summary_from_tls_geo_context(monkeypatch):
    monkeypatch.setenv(
        "FRAUD_KNOWN_JA3_HASHES",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    scorer = _StubFraudScorer()
    events = []
    result = evaluate_recommendation_fraud(
        tls_fingerprints={
            "source_ip": "203.0.113.5",
            "ja3_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "ja4_hash": "bbbbbbbbbbbbbbbb",
        },
        source_ip=None,
        image_hash="image-1",
        trace_id="trace-fraud-1",
        scorer=scorer,
        geoip_fn=lambda _ip: {"country": "US", "asn": 64512, "risk": 0.25},
        trace_fn=lambda **event: events.append(event),
    )

    assert result["summary"]["score"] == 0.91
    assert result["summary"]["level"] == "high"
    assert scorer.session_data["ja3_hash"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert scorer.session_data["ja4_hash"] == "bbbbbbbbbbbbbbbb"
    assert any(event["event_type"] == "fraud_score" for event in events)


def test_recommend_projects_last_geoip_country_and_asn():
    result = evaluate_recommendation_fraud(
        tls_fingerprints={"source_ip": "203.0.113.9"},
        source_ip=None,
        image_hash=None,
        trace_id="trace-fraud-2",
        scorer=_StubFraudScorer(score=0.33, level="low"),
        geoip_fn=lambda _ip: {"country": "US", "asn": 64512, "risk": 0.25},
    )

    assert result["persistence"] == {
        "last_ip_country": "US",
        "last_asn": 64512,
    }


def test_recommend_fraud_negative_path_handles_missing_geo_tls():
    scorer = _StubFraudScorer(score=0.05, level="minimal", signals={})
    result = evaluate_recommendation_fraud(
        tls_fingerprints={},
        source_ip=None,
        image_hash=None,
        trace_id="trace-fraud-3",
        scorer=scorer,
        geoip_fn=lambda _ip: {},
    )

    assert result["summary"]["level"] == "minimal"
    assert scorer.session_data.get("ja3_hash") is None
    assert scorer.session_data.get("ja4_hash") is None


def test_recommend_emits_system_error_trace_when_geoip_enrichment_fails():
    events = []
    result = evaluate_recommendation_fraud(
        tls_fingerprints={"source_ip": "203.0.113.19"},
        source_ip=None,
        image_hash=None,
        trace_id="trace-fraud-4",
        scorer=_StubFraudScorer(score=0.2, level="low", signals={}),
        geoip_fn=lambda _ip: (_ for _ in ()).throw(RuntimeError("geoip_down")),
        trace_fn=lambda **event: events.append(event),
    )

    assert result["errors"][0]["stage"] == "fraud_session.geoip"
    assert any(
        event["event_type"] == "system_error"
        and event["payload"]["stage"] == "fraud_session.geoip"
        for event in events
    )
