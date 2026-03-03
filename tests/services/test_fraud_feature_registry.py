from src.app.services.fraud_scorer import FraudScorer


def test_fraud_feature_registry_has_20_plus_signals():
    reg = FraudScorer.feature_registry()
    assert reg.get("version") == "fraud_feature_registry_v1"
    assert int(reg.get("feature_count") or 0) >= 20
    names = {f.get("name") for f in (reg.get("features") or [])}
    assert "shipping_address_clustered" in names
    assert "ip_velocity_spike" in names


def test_fraud_monitoring_snapshot_contains_coverage_and_group_rollup():
    scorer = FraudScorer()
    snapshot = scorer.monitoring_snapshot(
        {
            "shipping_address_clustered": True,
            "ip_velocity_spike": True,
            "manipulation_detected": False,
        },
        decision_outcome="false_positive",
    )
    assert 0.0 <= float(snapshot.get("feature_coverage") or 0.0) <= 1.0
    assert isinstance(snapshot.get("active_by_group"), dict)
    assert float(snapshot.get("estimated_false_positive_cost_usd") or 0.0) >= 0.0

