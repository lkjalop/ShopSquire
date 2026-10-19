"""Imported anomaly scorers must retain the mapping contract their callers use."""
import pytest

from src.app.analytics import isolation_forest


@pytest.mark.parametrize('name,features', [
    ('score_fraud', {'amount_cents': 1000, 'velocity': 2}),
    ('score_inventory', {'stock': 15, 'stock_velocity': 2}),
    ('score_agent_behavior', {'tool_calls': 4, 'errors': 0}),
])
def test_public_scorer_accepts_one_feature_mapping_and_returns_a_bounded_score(name, features):
    result = getattr(isolation_forest, name)(features)
    assert isinstance(result, dict)
    assert 0 <= result['score'] <= 1
    assert result['label'] in {'minimal', 'low', 'medium', 'high'}


def test_agent_anomaly_service_can_consume_the_public_scorer():
    from src.app.services.agent_behavior_anomaly import detect_behavior_anomaly
    result = detect_behavior_anomaly()
    assert 0 <= result['score'] <= 1
    assert isinstance(result['features'], dict)
