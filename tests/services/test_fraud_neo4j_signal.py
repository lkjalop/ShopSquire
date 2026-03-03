from src.app.services.fraud_scorer import BehavioralFraudDetector


def test_behavioral_detector_neo4j_cluster_signal(monkeypatch):
    def _fake_signal(**kwargs):
        return {"enabled": True, "source": "neo4j", "cluster_size": 6, "device_count": 3, "ring_risk": 0.82, "ring_hit": True}

    monkeypatch.setattr("src.app.services.fraud_scorer.shipping_address_cluster_signal", _fake_signal)
    session = {"shipping_address_hash": "addr-hash-1", "account_id": "u1", "device_fingerprint": "dev-1"}
    out = BehavioralFraudDetector().analyze_session(session)
    assert out.get("shipping_address_clustered") is True
    assert float(session.get("neo4j_ring_risk") or 0.0) > 0.5

